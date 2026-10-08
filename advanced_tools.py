"""Upstream DataSense helpers retained for opt-in advanced tools."""

import io
import json
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from langchain.prompts import PromptTemplate
from langchain.output_parsers import StructuredOutputParser, ResponseSchema
from langchain_core.output_parsers import StrOutputParser
from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent
from model_identity import configured_identity_answer, model_identity_instruction

# ----------------------------
# Helpers: Suggestion normalization
# ----------------------------
def normalize_nlq_suggestions(suggestions_obj) -> list:
    raw = suggestions_obj or {}
    items = raw.get("analytical_questions", []) if isinstance(raw, dict) else raw
    out = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, str):
                s = it.strip()
                if s:
                    out.append(s)
            elif isinstance(it, dict):
                # If dict, try common keys
                val = it.get("question") or it.get("text") or it.get("value")
                if isinstance(val, str) and val.strip():
                    out.append(val.strip())
    elif isinstance(items, str):
        # Attempt to split lines/bullets
        for line in items.splitlines():
            s = line.strip(" -•\t\r\n")
            if len(s) > 1:
                out.append(s)
    # Ensure at most 5, remove empties and dups
    dedup = []
    seen = set()
    for s in out:
        if s and s not in seen:
            seen.add(s)
            dedup.append(s)
    return dedup[:5]


def normalize_viz_suggestions(suggestions_obj) -> list:
    raw = suggestions_obj or {}
    items = raw.get("visualization_suggestions", []) if isinstance(raw, dict) else raw
    normalized = []

    def split_numbered_suggestions(text: str) -> list:
        """Split text like '1. ... 2. ... 3. ...' into individual suggestions"""
        import re
        suggestions = []

        # Enhanced pattern to handle: "1. **Title:** Description. 2. **Title:** Description."
        # Match: number, period, optional space, optional bold markers, title, colon, description
        # Pattern captures: number, optional bold title, and description
        pattern = r'(\d+)\.\s*(?:\*\*)?([^*:]+?)(?:\*\*)?:\s*(.+?)(?=\d+\.\s*(?:\*\*)?|$)'
        matches = re.finditer(pattern, text, re.DOTALL)

        for match in matches:
            num = match.group(1)
            title_part = match.group(2).strip()
            desc = match.group(3).strip()

            # Clean up title (remove bold markers, extra spaces)
            title_part = re.sub(r'\*\*', '', title_part).strip()

            # Extract chart type from title or description
            chart_type = "Visualization"
            desc_text = desc

            # Check if title contains chart type keywords
            title_lower = title_part.lower()
            chart_keywords = {
                'dashboard': 'Dashboard',
                'bar chart': 'Bar Chart',
                'boxplot': 'Boxplot',
                'stacked bar': 'Stacked Bar Chart',
                'line plot': 'Line Chart',
                'line chart': 'Line Chart',
                'scatter': 'Scatter Plot',
                'heatmap': 'Heatmap',
                'histogram': 'Histogram',
                'kde plot': 'KDE Plot'
            }

            for keyword, chart_name in chart_keywords.items():
                if keyword in title_lower:
                    chart_type = chart_name
                    break

            # Also check description for chart types
            if chart_type == "Visualization":
                desc_lower = desc.lower()
                # Look for patterns like "bar chart", "line plot", etc.
                for keyword, chart_name in chart_keywords.items():
                    if keyword in desc_lower:
                        chart_type = chart_name
                        break

                # Check for standalone chart words
                words = desc.split()
                for j, word in enumerate(words[:8]):  # Check first 8 words
                    word_lower = word.lower().rstrip('s')  # Remove plural
                    if word_lower in ['chart', 'plot', 'graph'] and j > 0:
                        # Get preceding words for context
                        context = ' '.join(words[max(0, j-2):j+1])
                        if 'bar' in context.lower():
                            chart_type = 'Bar Chart'
                        elif 'line' in context.lower():
                            chart_type = 'Line Chart'
                        elif 'scatter' in context.lower():
                            chart_type = 'Scatter Plot'
                        break

            # Use title as part of description if meaningful
            if title_part and len(title_part) > 3:
                if title_part not in desc_text:
                    desc_text = f"{title_part}: {desc_text}"

            suggestions.append({
                "type": chart_type,
                "description": desc_text.rstrip('. '),  # Remove trailing periods/spaces
                "original_title": title_part
            })

        # Fallback: if no matches found, try simpler pattern
        if not suggestions:
            # Try pattern without bold markers
            simple_pattern = r'(\d+)\.\s+([^:]+?):\s*(.+?)(?=\d+\.|$)'
            simple_matches = re.finditer(simple_pattern, text, re.DOTALL)
            for match in simple_matches:
                title_part = match.group(2).strip()
                desc = match.group(3).strip()
                chart_type = "Visualization"
                desc_text = desc

                # Extract chart type
                if any(word in title_part.lower() for word in ['chart', 'plot', 'graph', 'dashboard']):
                    words = title_part.split()
                    for word in words:
                        if word.lower() in ['bar', 'line', 'scatter', 'box', 'pie']:
                            chart_type = word.capitalize() + ' Chart'
                            break

                suggestions.append({
                    "type": chart_type,
                    "description": desc_text.rstrip('. '),
                    "original_title": title_part
                })

        return suggestions if suggestions else [{"type": "Visualization", "description": text}]

    def to_prompt(obj):
        if not obj:
            return None
        if isinstance(obj, str):
            return obj.strip()
        if isinstance(obj, dict):
            t = obj.get("type")
            desc = obj.get("description") or obj.get("desc") or obj.get("text")
            cols = obj.get("columns") or obj.get("cols") or []
            cols_txt = ", ".join([str(c) for c in cols]) if cols else "relevant columns"
            if t and desc:
                return f"Create a {t} — {desc} Use columns {cols_txt}."
            if desc:
                return f"{desc}"
            return None
        return None

    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                # Check if description contains numbered suggestions
                desc = it.get("description") or it.get("desc") or it.get("text") or ""
                if desc and (desc.count(".") > 2 and any(char.isdigit() for char in desc[:50])):
                    # Likely contains numbered suggestions - split them
                    split_items = split_numbered_suggestions(desc)
                    for split_item in split_items:
                        prompt = to_prompt(split_item)
                        normalized.append({
                            "type": split_item.get("type", it.get("type", "Visualization")),
                            "description": split_item.get("description", ""),
                            "original_title": split_item.get("original_title", ""),
                            "columns": it.get("columns") or it.get("cols") or [],
                            "prompt": prompt or "",
                        })
                else:
                    # Normal dict item
                    prompt = to_prompt(it)
                    normalized.append({
                        "type": it.get("type") or "Visualization",
                        "description": it.get("description") or it.get("desc") or it.get("text") or "",
                        "columns": it.get("columns") or it.get("cols") or [],
                        "prompt": prompt or "",
                        "original_title": it.get("original_title", ""),
                    })
            else:
                s = str(it).strip()
                if s:
                    # Check if it's a numbered list
                    if s.count(".") > 2 and any(char.isdigit() for char in s[:50]):
                        split_items = split_numbered_suggestions(s)
                        for split_item in split_items:
                            normalized.append({
                                "type": split_item.get("type", "Visualization"),
                                "description": split_item.get("description", ""),
                                "original_title": split_item.get("original_title", ""),
                                "columns": [],
                                "prompt": split_item.get("description", ""),
                            })
                    else:
                        normalized.append({
                            "type": "Visualization",
                            "description": s,
                            "columns": [],
                            "prompt": s,
                            "original_title": "",
                        })
    elif isinstance(items, str):
        s = items.strip()
        if s:
            # Check if it's a numbered list
            if s.count(".") > 2 and any(char.isdigit() for char in s[:50]):
                split_items = split_numbered_suggestions(s)
                for split_item in split_items:
                    normalized.append({
                        "type": split_item.get("type", "Visualization"),
                        "description": split_item.get("description", ""),
                        "original_title": split_item.get("original_title", ""),
                        "columns": [],
                        "prompt": split_item.get("description", ""),
                    })
            else:
                normalized.append({
                    "type": "Visualization",
                    "description": s,
                    "columns": [],
                    "prompt": s,
                    "original_title": "",
                })

    out = []
    seen_prompts = set()
    for obj in normalized:
        p = obj.get("prompt", "").strip()
        if p and p not in seen_prompts:
            seen_prompts.add(p)
            out.append(obj)
    return out[:5]


# ----------------------------
# Helpers: Code safety for viz (aligns with Visual.py intent)
# ----------------------------
BLOCKED_KEYWORDS = [
    "import os", "import sys", "subprocess", "shutil", "open(",
    "socket", "requests", "eval(", "exec(", "os.system", "pip install",
    "__import__", "del ", "input(", "exit(", "quit(", "globals", "locals"
]

def is_code_safe(code: str) -> tuple[bool, str | None]:
    for bad in BLOCKED_KEYWORDS:
        if bad.lower() in code.lower():
            return False, f"Unsafe code detected: `{bad}`"
    return True, None


# ----------------------------
# EDA logic (mirrors EDA.py without altering it)
# ----------------------------
def run_eda(df: pd.DataFrame) -> dict:
    eda_results = {}
    eda_results["shape"] = df.shape
    eda_results["columns"] = list(df.columns)
    eda_results["dtypes"] = {k: str(v) for k, v in df.dtypes.to_dict().items()}
    try:
        # memory_usage_string is not a public API; fallback gracefully
        info_buf = io.StringIO()
        df.info(buf=info_buf)
        eda_results["memory_usage"] = info_buf.getvalue()
    except Exception:
        eda_results["memory_usage"] = ""

    eda_results["missing_count_per_column"] = df.isnull().sum().to_dict()
    eda_results["missing_percent_per_column"] = (df.isnull().sum() / len(df) * 100).round(3).to_dict()
    eda_results["total_missing_rows"] = int(df.isnull().sum().sum())

    numeric_stats = {}
    for col in df.select_dtypes(include=["int64", "float64"]).columns:
        numeric_stats[col] = {
            "mean": float(df[col].mean()) if pd.notnull(df[col].mean()) else None,
            "min": float(df[col].min()) if pd.notnull(df[col].min()) else None,
            "max": float(df[col].max()) if pd.notnull(df[col].max()) else None,
            "std": float(df[col].std()) if pd.notnull(df[col].std()) else None,
            "q1": float(df[col].quantile(0.25)) if pd.notnull(df[col].quantile(0.25)) else None,
            "median": float(df[col].quantile(0.5)) if pd.notnull(df[col].quantile(0.5)) else None,
            "q3": float(df[col].quantile(0.75)) if pd.notnull(df[col].quantile(0.75)) else None,
        }
    eda_results["numeric_stats"] = numeric_stats

    categorical_stats = {}
    for col in df.select_dtypes(include=["object"]).columns:
        value_counts = df[col].value_counts().head()
        categorical_stats[col] = {
            "unique_count": int(df[col].nunique(dropna=True)),
            "top_values": {str(k): int(v) for k, v in value_counts.to_dict().items()},
        }
    eda_results["categorical_stats"] = categorical_stats

    numeric_df = df.select_dtypes(include=["int64", "float64"]).copy()
    try:
        eda_results["correlation_matrix"] = json.loads(numeric_df.corr(numeric_only=True).to_json()) if not numeric_df.empty else {}
    except Exception:
        eda_results["correlation_matrix"] = {}

    eda_results["duplicate_rows"] = int(df.duplicated().sum())
    eda_results["unique_values_per_column"] = {col: int(df[col].nunique(dropna=True)) for col in df.columns}

    # IQR outliers
    outlier_summary = {}
    for col in df.select_dtypes(include=["int64", "float64"]).columns:
        Q1 = df[col].quantile(0.25)
        Q3 = df[col].quantile(0.75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        outliers = df[(df[col] < lower_bound) | (df[col] > upper_bound)]
        outlier_summary[col] = int(len(outliers))
    eda_results["outliers"] = outlier_summary
    return eda_results


# ----------------------------
# Dataframe details string (used by LLM prompts)
# ----------------------------
def get_dataframe_details(df: pd.DataFrame, n_rows: int = 5) -> str:
    details = f"""
Columns: {', '.join(df.columns.tolist())}

Data Types:
{df.dtypes.to_string()}

Shape: {df.shape[0]} rows × {df.shape[1]} columns

Sample Data:
{df.head(n_rows).to_string(index=False)}
"""
    return details.strip()


# ----------------------------
# Insight suggestion chain (mirrors Insight_suggestor.py)
# ----------------------------
def get_insight_suggestions(model, df: pd.DataFrame):
    dataframe_details = get_dataframe_details(df)
    response_schemas = [
        ResponseSchema(name="analytical_questions", description="List of 5 insightful natural language queries for analysis."),
        ResponseSchema(name="visualization_suggestions", description="List of 5 visualizations with chart types and columns to plot."),
    ]
    parser = StructuredOutputParser.from_response_schemas(response_schemas)
    format_instructions = parser.get_format_instructions()
    template = PromptTemplate(
        template="""
You are a skilled Python data analyst and EDA expert.

Your job is to carefully study the given dataframe details and suggest useful **analytical questions** and **visualizations**
that can help a data analyst gain deeper insights into this dataset.

### Instructions:
1. Understand the dataframe details (column names, datatypes, and example values if present).
2. Suggest exactly **5 insightful analytical questions** that can be answered using the data.
   - These should sound like natural language queries (NLQ), not SQL or code.
3. Suggest exactly **5 visualizations** that would reveal key patterns.
   - Mention the type of visualization (e.g., bar chart, boxplot, scatter plot, line chart, heatmap).
   - Specify which columns or relationships to visualize.
4. If possible, align the insights with the domain.

### DataFrame Details:
{dataframe_details}

### Output Format:
{format_instructions}
""",
        input_variables=["dataframe_details", "format_instructions"],
    )
    chain = template | model | parser
    result = chain.invoke({"dataframe_details": dataframe_details, "format_instructions": format_instructions})
    return result


# ----------------------------
# NLQ answering: use agent executor to execute pandas code (like NLQ.ipynb)
# ----------------------------
def answer_nlq_text(model, df: pd.DataFrame, question: str, *, model_identity=None) -> str:
    identity_answer = configured_identity_answer(question, model_identity)
    if identity_answer:
        return identity_answer
    system_prompt = """
You are a safe data analysis assistant.
You are allowed to manipulate data using pandas operations like filtering, grouping, sorting, merging, etc.
You must **not** execute or suggest any commands that:
- read, write, or delete files other than explicitly mentioned CSV outputs
- import or use system libraries (os, sys, subprocess, shutil, socket, requests)
- run shell commands, install packages, or use eval/exec
- access the internet or external resources

If the user asks for something unsafe, politely refuse.
When answering, provide specific numbers and results from the data, not approximations.
""" + "\n" + model_identity_instruction(model_identity)

    try:
        # Create the dataframe agent with safety instructions (mirrors NLQ.ipynb)
        agent = create_pandas_dataframe_agent(
            model,
            df.copy(deep=True),
            verbose=False,  # Set to True if you want to see tool invocations
            allow_dangerous_code=True,  # Required for pandas agent
            agent_type="openai-tools",  # Ensures reasoning with tool use
            prefix=system_prompt,
            max_iterations=4,
            max_execution_time=120,
        )
        result = agent.invoke(question)
        # Agent returns a dict with 'input' and 'output' keys
        if isinstance(result, dict):
            return result.get("output", str(result))
        return str(result)
    except Exception as e:
        return f"Error executing NLQ: {str(e)}"


# ----------------------------
# Visualization generation: produce pyplot/seaborn code and execute safely
# ----------------------------
def generate_and_render_chart(model, df: pd.DataFrame, viz_request: str):
    details = get_dataframe_details(df)
    prompt = PromptTemplate(
        template="""
You are a Python visualization assistant.
Generate ONLY executable matplotlib/seaborn code to create the requested visualization from DataFrame `df`.

Rules:
- Use `import matplotlib.pyplot as plt` and `import seaborn as sns` ONLY if needed inside code.
- Do NOT read/write files. Do NOT show() the plot. Do NOT print.
- Always create a figure and axis: `fig, ax = plt.subplots(figsize=(8,5))` and plot on `ax`.
- Title and label axes when sensible.

### DataFrame Details:
{details}

### Visualization Request:
{viz_request}

Output only raw code, no markdown.
""",
        input_variables=["details", "viz_request"],
    )
    chain = prompt | model | StrOutputParser()
    code = chain.invoke({"details": details, "viz_request": viz_request})

    # Remove any import statements to avoid blocked imports in restricted exec
    sanitized_lines = []
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            continue
        sanitized_lines.append(line)
    code = "\n".join(sanitized_lines)

    # Safety check like Visual.py
    ok, msg = is_code_safe(code)
    if not ok:
        return None, code, msg

    # Execute safely
    safe_builtins = {
        "len": len,
        "range": range,
        "min": min,
        "max": max,
        "sum": sum,
        "abs": abs,
        "round": round,
        "int": int,
        "float": float,
        "str": str,
        "list": list,
        "dict": dict,
        "set": set,
        "tuple": tuple,
        "enumerate": enumerate,
        "zip": zip,
        "sorted": sorted,
    }
    safe_globals = {"__builtins__": safe_builtins}
    # Provide a default fig/ax for code that references ax without creating it
    default_fig, default_ax = plt.subplots(figsize=(8, 5))
    safe_locals = {"df": df.copy(deep=True), "pd": pd, "plt": plt, "sns": sns, "fig": default_fig, "ax": default_ax}
    # Ensure a fresh figure context per run
    plt.close("all")
    try:
        exec(code, safe_globals, safe_locals)
        # Try to get fig from locals (recommended), else fallback to current figure
        fig = safe_locals.get("fig", plt.gcf())
        return fig, code, None
    except Exception as e:
        return None, code, str(e)


# ----------------------------
# Dataframe manipulation: reuse core prompt/guardrails from dataframe_manipulation.py
# ----------------------------
def manipulate_dataframe_with_llm(model, df: pd.DataFrame, user_request: str):
    dataframe_details = get_dataframe_details(df)
    data_manipulation_prompt = PromptTemplate(
        template="""
You are a **safe Python data manipulation assistant**.

The current DataFrame is named `df`.

Your job:
Generate **only executable pandas code** that performs the user request.

### Rules:
- You may use: filtering, grouping, sorting, adding/removing columns, renaming, merging, etc.
- You MUST NOT import or use modules like os, sys, subprocess, shutil, socket, or requests.
- DO NOT perform any file I/O.
- DO NOT use eval(), exec(), or shell commands.
- DO NOT print anything or explain steps — only output pure Python code.
- Modify or create a DataFrame named `df`. Do not save files.

### DataFrame Details:
{dataframe_details}

### User Request:
{user_query}

Output only raw code — no markdown, no explanation.
""",
        input_variables=["dataframe_details", "user_query"],
    )
    chain = data_manipulation_prompt | model | StrOutputParser()
    code = chain.invoke({"dataframe_details": dataframe_details, "user_query": user_request})

    safe_locals = {"df": df.copy(deep=True), "pd": pd}
    try:
        exec(code, {"__builtins__": {}}, safe_locals)
        new_df = safe_locals["df"]
        return new_df, code, None
    except Exception as e:
        return df, code, str(e)
