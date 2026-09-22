"""OCR v1.6.5 接收方映射；仅抄录协议事实，不扩展模型选择。"""
# 来源：alibaba/open-code-review v1.6.5 internal/llm/providers.go。
PRESETS = {
    "anthropic": ("https://api.anthropic.com", "anthropic", "ANTHROPIC_API_KEY"),
    "openai": ("https://api.openai.com/v1", "openai", "OPENAI_API_KEY"),
    "dashscope": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "openai", "DASHSCOPE_API_KEY"),
    "dashscope-tokenplan": ("https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1", "openai", "DASHSCOPE_TOKENPLAN_KEY"),
    "volcengine": ("https://ark.cn-beijing.volces.com/api/v3", "openai", "ARK_API_KEY"),
    "deepseek": ("https://api.deepseek.com", "openai", "DEEPSEEK_API_KEY"),
    "tencent-tokenhub": ("https://tokenhub.tencentmaas.com/v1", "openai", "TENCENT_TOKENHUB_API_KEY"),
    "hy-tokenplan": ("https://api.lkeap.cloud.tencent.com/plan/v3", "openai", "TENCENT_HUNYUAN_TOKENPLAN_KEY"),
    "kimi": ("https://api.moonshot.cn/v1", "openai", "MOONSHOT_API_KEY"),
    "z-ai": ("https://open.bigmodel.cn/api/paas/v4", "openai", "Z_AI_API_KEY"),
    "mimo": ("https://api.xiaomimimo.com/v1", "openai", "MIMO_API_KEY"),
    "minimax": ("https://api.minimaxi.com/v1", "openai", "MINIMAX_API_KEY"),
    "baidu-qianfan": ("https://qianfan.baidubce.com/v2", "openai", "QIANFAN_API_KEY"),
}
