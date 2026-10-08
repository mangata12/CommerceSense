"""Model identity comes from application configuration, never self-reporting."""

import json
import re


def public_model_identity(provider, model_name):
    return {"provider": str(provider), "model_name": str(model_name).strip()}


def identity_question(question):
    text = re.sub(r"[\s，。？！、,.?!：:]+", "", question).lower()
    questions = {
        "你是什么模型", "你用的是什么模型", "你使用的是什么模型", "你现在是什么模型",
        "你当前是什么模型", "你用的什么模型", "你是什么大模型", "你是什么大语言模型",
        "你基于什么模型", "你调用的是什么模型", "你实际是什么模型", "你是谁",
        "当前使用的是什么模型", "当前调用的是什么模型", "当前模型是什么", "模型是什么",
        "whatmodelareyou", "whatmodelareyouusing", "whichmodelareyouusing", "whoareyou",
    }
    text = re.sub(r"^(?:请问|请告诉我|告诉我)", "", text)
    if text in questions:
        return True
    return bool(re.fullmatch(
        r"(?:你(?:是|是不是|用的是|使用的是)|areyou)(?:deepseek(?:-chat|-reasoner)?|claude(?:[\w.-]*)|gpt(?:[\w.-]*)|gemini(?:[\w.-]*))(?:模型)?(?:吗|么)?", text))


def configured_identity_answer(question, identity):
    if not identity or not identity_question(question):
        return None
    return (f"当前应用配置的模型服务为 **{identity['provider']}**，模型名称为 **{identity['model_name']}**。"
            "此信息来自应用的调用配置，不依赖模型自报身份。")


def model_identity_instruction(identity=None):
    if not identity:
        return "模型身份以应用调用配置为准；未提供配置时不要推断或自称某个服务商、模型。"
    return ("当前应用调用配置：" + json.dumps(identity, ensure_ascii=False) +
            "。回答自身模型身份时以此配置为准，不根据历史回答或训练文本自报其他模型；配置不等于对服务端内部实现的独立鉴定。")
