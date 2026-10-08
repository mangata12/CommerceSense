"""Dataset lifecycle independent of Streamlit, so reruns cannot overwrite mapping."""

from hashlib import sha256

from commerce_data import infer_field_mapping, load_commerce_file, prepare_commerce_data


CHAT_KEYS = {
    "commerce_messages", "commerce_tool_results", "commerce_agent_last_answer",
    "commerce_chat_context", "commerce_retry_question", "commerce_chat_input",
}

RESULT_KEYS = CHAT_KEYS | {
    "commerce_agent_last_answer", "commerce_messages", "commerce_tool_results", "commerce_report",
    "commerce_current_period", "commerce_product_filter", "commerce_agent_question",
    "_nlq_last_answer", "_nlq_prefill", "_nlq_suggestions", "nlq_question",
    "_viz_prefill", "_viz_suggestions", "viz_request",
    "commerce_advanced_result", "commerce_advanced_request",
    "commerce_previous_period", "commerce_comparison_anchor",
}


def clear_analysis(state):
    for key in RESULT_KEYS:
        state.pop(key, None)


def clear_conversation(state):
    for key in CHAT_KEYS:
        state.pop(key, None)


def load_dataset(state, uploaded_file) -> bool:
    uploaded_file.seek(0)
    fingerprint = sha256(uploaded_file.read()).hexdigest()
    uploaded_file.seek(0)
    # The extension determines the parser; filename alone never triggers a reload.
    fingerprint += ":" + uploaded_file.name.rsplit(".", 1)[-1].lower()
    if state.get("commerce_file_fingerprint") == fingerprint:
        return False
    raw = load_commerce_file(uploaded_file)
    if not raw.columns.is_unique:
        raise ValueError("列名必须唯一")
    clear_analysis(state)
    for key in list(state):
        if key.startswith("commerce_mapping_"):
            state.pop(key, None)
    state["commerce_currency_choice"] = "请选择币种"
    state["commerce_file_fingerprint"] = fingerprint
    state["commerce_raw_df"] = raw
    state["commerce_mapping"] = infer_field_mapping(list(raw.columns))
    state["commerce_applied_mapping"] = None
    state["commerce_currency"] = None
    state["commerce_quality"] = None
    state["commerce_standard_df"] = None
    state["commerce_excluded_df"] = None
    state["df"] = None
    return True


def apply_dataset_mapping(state, mapping, currency):
    prepared = prepare_commerce_data(state["commerce_raw_df"], mapping, currency)
    if prepared["quality"]["missing_required"]:
        raise ValueError("请映射订单号、数量、单价、订单时间")
    clear_analysis(state)
    state["commerce_mapping"] = dict(mapping)
    state["commerce_applied_mapping"] = dict(mapping)
    state["commerce_currency"] = currency
    state["commerce_standard_df"] = prepared["data"]
    state["commerce_quality"] = prepared["quality"]
    state["commerce_excluded_df"] = prepared["excluded"]
    state["df"] = prepared["data"]
    return prepared
