"""OCR 正式 CLI 的输出、配置与双执行模式边界。"""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import signal
import shutil
import subprocess
import time
from urllib.parse import urlsplit

from .consent import digest
from .git_snapshot import git_env
from .providers import PRESETS


@dataclass(repr=False)
class Endpoint:
    """凭据只驻留内存，不进入 repr、状态或对话。"""
    public: dict
    token: str = field(repr=False)
    config_path: Path = field(repr=False)

    def __repr__(self):
        return "Endpoint(public=" + repr(self.public) + ", token=<redacted>)"


def resolve(config_path=None, environment=None):
    """遵循 v1.6.5 的配置优先级；未能安全解析时拒绝猜测接收方。"""
    env = os.environ if environment is None else environment
    path = Path(config_path) if config_path is not None else Path.home() / ".opencodereview/config.json"
    if path.exists() and (path.is_symlink() or path.stat().st_size > 1024 * 1024):
        raise ValueError("unsupported_config_file")
    try:
        cfg = json.loads(path.read_text()) if path.exists() else {}
    except (ValueError, OSError) as exc:
        raise ValueError("invalid_engine_config") from exc
    if not isinstance(cfg, dict):
        raise ValueError("invalid_engine_config")
    if any(not isinstance(cfg.get(key, {}), dict) for key in
           ("telemetry", "providers", "custom_providers", "llm")):
        raise ValueError("invalid_engine_config")
    if "provider" in cfg and not isinstance(cfg["provider"], str):
        raise ValueError("invalid_engine_config")
    if cfg.get("telemetry", {}).get("enabled"):
        raise ValueError("telemetry_must_be_disabled_for_review")
    if (path.parent / "rule.json").exists():
        raise ValueError("unsupported_global_rules: external rule resolution requires separate review")
    # 不静默选择上游内置服务商地址；必须能确定配置的有效接收方。
    provider = cfg.get("provider")
    if provider:
        preset = PRESETS.get(provider.strip().lower())
        entry = cfg.get("providers" if preset else "custom_providers", {}).get(provider)
        if not isinstance(entry, dict):
            raise ValueError("unsupported_provider_config")
        url = entry.get("url") or (preset[0] if preset else None)
        protocol = entry.get("protocol") or (preset[1] if preset else None)
        token = entry.get("api_key") or (env.get(preset[2]) if preset else None)
        model = entry.get("model") or cfg.get("model")
        if protocol == "anthropic" and isinstance(url, str) and url and "/v1/" not in url:
            url = url.rstrip("/") + "/v1/messages"
    else:
        entry = cfg.get("llm", {})
        url, token, model = (entry.get(k) for k in ("url", "auth_token", "model"))
        protocol = "anthropic" if entry.get("use_anthropic", True) else "openai"
        if not all((url, token, model)):
            entry = {}
            url, token, model = (env.get(k) for k in ("OCR_LLM_URL", "OCR_LLM_TOKEN", "OCR_LLM_MODEL"))
            protocol = "anthropic" if env.get("OCR_USE_ANTHROPIC", "true").lower() in {"true", "1", "yes"} else "openai"
    if entry.get("extra_headers") or entry.get("extra_body") or env.get("OCR_LLM_EXTRA_HEADERS"):
        raise ValueError("unsupported_extra_engine_parameters")
    if not all(isinstance(x, str) and x.strip() for x in (url, token, model)):
        raise ValueError("configuration_required: explicit OCR endpoint, token and model")
    if protocol not in {"anthropic", "openai"}:
        raise ValueError("unsupported_protocol")
    endpoint = urlsplit(url)
    if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        raise ValueError("invalid_endpoint")
    model = re.sub(r"\[\d+m\]$", "", model)
    public = {"endpoint": url, "model": model, "protocol": protocol,
              "context_policy": "tracked-candidate", "config_digest": digest({
                  "config": cfg, "endpoint": url, "model": model, "protocol": protocol,
                  "auth_header": env.get("OCR_LLM_AUTH_HEADER", "")})}
    return Endpoint(public, token, path)


def normalize(output):
    """只接受单个合法 JSON 结果；无问题不等于完整覆盖。"""
    try:
        raw = json.loads(output)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_engine_output") from exc
    statuses = {"success": "success", "complete": "success",
                "completed_with_warnings": "partial",
                "completed_with_errors": "partial", "skipped": "skipped"}
    if not isinstance(raw, dict) or raw.get("status") not in statuses or "comments" not in raw:
        raise ValueError("invalid_engine_status")
    comments = raw["comments"] if raw["comments"] is not None else []
    warnings = raw.get("warnings") or []
    if not isinstance(comments, list) or not isinstance(warnings, list):
        raise ValueError("invalid_engine_lists")
    findings = []
    for comment in comments:
        if not isinstance(comment, dict):
            raise ValueError("invalid_finding")
        path = comment.get("path")
        if (not isinstance(path, str) or not path or PurePosixPath(path).is_absolute()
                or ".." in PurePosixPath(path).parts or "\\" in path):
            raise ValueError("invalid_finding_path")
        if (not isinstance(comment.get("content"), str) or not comment["content"]
                or type(comment.get("start_line")) is not int
                or type(comment.get("end_line")) is not int
                or not 1 <= comment["start_line"] <= comment["end_line"]):
            raise ValueError("invalid_finding_evidence")
        findings.append({k: comment.get(k, "unknown" if k in {"severity", "category"} else "")
                         for k in ("path", "content", "start_line", "end_line", "existing_code",
                                   "suggestion_code", "severity", "category")})
    if any(not isinstance(w, dict) or not isinstance(w.get("type"), str) for w in warnings):
        raise ValueError("invalid_warning")
    execution = statuses[raw["status"]]
    if warnings and execution == "success":
        execution = "partial"
    summary = raw.get("summary") or {}
    if not isinstance(summary, dict):
        raise ValueError("invalid_summary")
    reviewed = summary.get("files_reviewed", 0)
    if type(reviewed) is not int or reviewed < 0:
        raise ValueError("invalid_reviewed_count")
    if execution == "success" and reviewed == 0:
        execution = "partial"
    return {"version": 1, "execution_status": execution,
            "coverage_status": "none" if execution == "skipped" else "limited",
            "findings": findings, "warnings": warnings, "files_reviewed": reviewed,
            "coverage_note": "统计不证明逐文件完整覆盖；无问题不构成安全保证。"}


def run_process(args, cwd, env, *, timeout=600, max_bytes=2 * 1024 * 1024, cancelled=lambda: False):
    """有界捕获双管道，超时/撤销时终止进程组，不回显原始诊断。"""
    process = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            deadline = time.monotonic() + timeout
            total = 0
            while selector.get_map() or process.poll() is None:
                if cancelled():
                    raise ValueError("cancelled")
                if time.monotonic() >= deadline:
                    raise ValueError("timeout")
                for key, _ in selector.select(0.05):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("output_limit")
                    buffers[key.data].extend(chunk)
            return process.wait(), buffers["stdout"].decode("utf-8"), buffers["stderr"].decode("utf-8", errors="replace")
    finally:
        # 即使父进程先退出也清理同组子进程，避免超时后仍产生请求。
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # macOS 上父进程退出后，组号可能已不可操作；不以清理错误覆盖真实审查结果。
            # 若父进程仍在，至少直接终止它，避免 wait 无限阻塞。
            if process.poll() is None:
                process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()


class OCR:
    """按能力协商 OCR；配置路径/环境注入只用于离线测试。"""

    def __init__(self, command=None, *, config_path=None, environment=None):
        self.command = list(command or ["ocr"])
        self.config_path = config_path
        self.environment = dict(os.environ if environment is None else environment)

    def configuration(self):
        return resolve(self.config_path, self.environment)

    def env(self):
        # 清除环境开启的遥测与通用模型回退；文件中开启遥测会被 configuration 拒绝。
        env = {k: v for k, v in self.environment.items()
               if (not k.startswith(("OTEL_", "GIT_", "ANTHROPIC_")) or k == "ANTHROPIC_API_KEY")
               and k not in {"OCR_ENABLE_TELEMETRY", "OCR_CONTENT_LOGGING", "OCR_CONFIG_PATH"}}
        env.update({k: v for k, v in git_env().items() if k.startswith("GIT_")})
        return env

    def capabilities(self, cwd):
        """只探测 CLI 接口，不读取 LLM 配置，也不执行连接测试。"""
        code, stdout, _ = run_process(self.command + ["--version"], cwd, self.env(), timeout=5)
        match = re.search(r"\bopen-code-review v?(\d+\.\d+\.\d+)(?:\s|$)", stdout)
        if code or not match:
            raise ValueError("unsupported_engine_version")
        version = match.group(1)

        def supports(arguments, flags):
            result, help_text, _ = run_process(self.command + arguments + ["--help"], cwd,
                                               self.env(), timeout=5)
            return result == 0 and all(flag in help_text for flag in flags)

        delegated = (supports(["delegate", "preview"], ["--repo", "--commit", "--format"])
                     and supports(["delegate", "rule"], ["--repo", "--commit", "--format"]))
        managed = supports(["review"],
                           ["--repo", "--commit", "--format", "--audience", "--preview", "--output"])
        return {"version": version, "delegated": delegated, "managed": managed}

    def scope(self, mode, *, host, host_model):
        """生成授权范围；委托模式不要求 OCR 自身配置模型。"""
        if mode == "delegated":
            if not isinstance(host, str) or not host.strip():
                raise ValueError("invalid_host")
            model = host_model if isinstance(host_model, str) and host_model.strip() else "current-session-model"
            public = {
                "endpoint": "host-agent://" + host.strip().lower(),
                "model": model,
                "context_policy": "tracked-candidate",
                "execution_mode": "delegated",
            }
            public["config_digest"] = digest(public)
            return public
        if mode == "ocr-managed":
            public = dict(self.configuration().public)
            public["execution_mode"] = mode
            return public
        raise ValueError("unsupported_execution_mode")

    @staticmethod
    def _safe_path(value):
        return (isinstance(value, str) and bool(value)
                and not PurePosixPath(value).is_absolute()
                and ".." not in PurePosixPath(value).parts and "\\" not in value)

    def _require_telemetry_off(self):
        """Delegation 不要求 LLM 配置；但遥测开启会外发宿主元数据并污染输出流。"""
        path = Path(self.config_path) if self.config_path is not None else Path.home() / ".opencodereview/config.json"
        if not path.exists():
            return
        if path.is_symlink() or path.stat().st_size > 1024 * 1024:
            raise ValueError("unsupported_config_file")
        try:
            cfg = json.loads(path.read_text())
        except (ValueError, OSError) as exc:
            raise ValueError("invalid_engine_config") from exc
        if not isinstance(cfg, dict) or not isinstance(cfg.get("telemetry", {}), dict):
            raise ValueError("invalid_engine_config")
        if cfg.get("telemetry", {}).get("enabled"):
            raise ValueError("telemetry_must_be_disabled_for_review")

    def delegate(self, snapshot, *, cancelled=lambda: False, timeout=60):
        """让 OCR 选择文件和解析规则，实际语义审查交给宿主智能体。"""
        self._require_telemetry_off()
        capabilities = self.capabilities(snapshot.path)
        if not capabilities["delegated"]:
            raise ValueError("delegation_not_supported")
        common = ["--repo", str(snapshot.path), "--commit", snapshot.commit, "--format", "json"]
        code, preview_text, _ = run_process(self.command + ["delegate", "preview"] + common,
                                            snapshot.path, self.env(), timeout=timeout,
                                            cancelled=cancelled)
        if code:
            raise ValueError("delegate_preview_failed")
        try:
            preview = json.loads(preview_text)
            reviewable = preview["reviewable_files"]
            excluded = preview["excluded_files"]
            if (not isinstance(preview, dict)
                    or preview.get("schema_version", preview.get("version")) != "1"
                    or not isinstance(reviewable, list) or not isinstance(excluded, list)
                    or any(not isinstance(item, dict) or not self._safe_path(item.get("path"))
                           or not isinstance(item.get("status"), str) for item in reviewable)
                    or any(not isinstance(item, dict) or not self._safe_path(item.get("path"))
                           for item in excluded)):
                raise ValueError()
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("invalid_delegate_preview") from exc
        paths = [item["path"] for item in reviewable]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate_delegate_path")
        groups = []
        if paths:
            code, rule_text, _ = run_process(
                self.command + ["delegate", "rule"] + common + paths,
                snapshot.path, self.env(), timeout=timeout, cancelled=cancelled)
            if code:
                raise ValueError("delegate_rule_failed")
            try:
                rule_result = json.loads(rule_text)
                groups = rule_result["groups"]
                if (not isinstance(rule_result, dict)
                        or rule_result.get("schema_version", rule_result.get("version")) != "1"
                        or not isinstance(groups, list)):
                    raise ValueError()
                covered = []
                for group in groups:
                    gid = group.get("group_id") if isinstance(group, dict) else None
                    # 真实 v1.12.9 的 group_id 是整数，旧接口是字符串；两者都接受。
                    if (not isinstance(group, dict)
                            or not ((isinstance(gid, str) and gid) or type(gid) is int)
                            or any(not isinstance(group.get(key), str) or not group[key]
                                   for key in ("source", "pattern", "rule"))
                            or not isinstance(group.get("files"), list)
                            or any(not self._safe_path(path) for path in group["files"])):
                        raise ValueError()
                    covered.extend(group["files"])
                if sorted(covered) != sorted(paths):
                    raise ValueError()
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError("invalid_delegate_rules") from exc
        return {
            "version": 1,
            "engine_version": capabilities["version"],
            "reviewable_files": reviewable,
            "excluded_files": excluded,
            "rule_groups": groups,
            "coverage_required": paths,
        }

    def review_managed(self, snapshot, endpoint, *, output_dir, cancelled=lambda: False,
                       timeout=600):
        """由 OCR 调用已配置模型，并仅从权限受限的结果文件读取报告。"""
        if self.configuration().public != endpoint.public:
            raise ValueError("engine_configuration_changed")
        capabilities = self.capabilities(snapshot.path)
        if not capabilities["managed"]:
            raise ValueError("managed_review_not_supported")
        output_dir = Path(output_dir)
        if output_dir.exists() or output_dir.is_symlink():
            raise ValueError("unsafe_output_directory")
        output_dir.mkdir(mode=0o700, parents=False)
        result_path = output_dir / "result.json"
        args = self.command + ["review", "--repo", str(snapshot.path), "--commit", snapshot.commit,
                               "--format", "json", "--audience", "agent"]
        try:
            if (snapshot.path / ".opencodereview/rule.json").exists():
                raise ValueError("unsupported_project_rules")
            code, preview_text, _ = run_process(args + ["--preview"], snapshot.path, self.env(),
                                                timeout=30, cancelled=cancelled)
            if code:
                raise ValueError("engine_preview_failed")
            try:
                preview = json.loads(preview_text)
                files = preview["files"] or []
                if (not isinstance(files, list) or any(not isinstance(item, dict)
                        or not self._safe_path(item.get("path"))
                        or type(item.get("will_review")) is not bool for item in files)):
                    raise ValueError()
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError("invalid_engine_preview") from exc
            reviewable = sum(item["will_review"] for item in files)
            if reviewable == 0:
                return {"version": 1, "execution_status": "skipped", "coverage_status": "none",
                        "findings": [], "warnings": [{"type": "all_files_filtered"}],
                        "files_reviewed": 0, "engine_version": capabilities["version"],
                        "preview": files}
            if self.configuration().public != endpoint.public:
                raise ValueError("engine_configuration_changed")
            code, _, _ = run_process(args + ["--output", str(result_path)], snapshot.path,
                                     self.env(), timeout=timeout, cancelled=cancelled)
            if code:
                raise ValueError("engine_process_failed")
            if (not result_path.is_file() or result_path.is_symlink()
                    or result_path.stat().st_size > 2 * 1024 * 1024):
                raise ValueError("invalid_engine_output_file")
            report = normalize(result_path.read_text().replace(endpoint.token, "[REDACTED]"))
            if report["files_reviewed"] != reviewable and report["execution_status"] == "success":
                report["execution_status"] = "partial"
                report["warnings"].append({"type": "coverage_count_mismatch"})
            report.update(engine_version=capabilities["version"], preview=files)
            return report
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)
