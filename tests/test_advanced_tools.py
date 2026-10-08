"""Real plotting and LangChain execution with deterministic model transport."""

import io
from pathlib import Path
import unittest
from unittest.mock import patch

import matplotlib.pyplot as plt
import pandas as pd
from langchain_core.messages import AIMessage
from streamlit.testing.v1 import AppTest
from advanced_tools import answer_nlq_text, generate_and_render_chart, AdvancedQueryError
from advanced_routing import resolve_advanced_mode
from commerce_session import load_dataset, apply_dataset_mapping
from fake_chat_model import ScriptedChatModel, tool_call
from test_commerce_lifecycle import upload


BAR_CODE = """```python
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(8,5))
minor = (df['quantity'] * df['unit_price'] * 100).map(int)
values = minor.groupby(df['product_id']).sum() / 100
labels = [key for key in values.index if key in df['product_id'].values]
ax.bar(labels, values.values)
ax.set_title('Net sales CNY by product ID')
```"""


class AdvancedToolTests(unittest.TestCase):
    def setUp(self):
        self.state = {}
        load_dataset(self.state, upload(
            "订单编号,商品编号,商品名称,数量,单价,日期\n"
            "001,01,杯子,3,0.10,2026-09-01\n"
            "002,02,杯子,1,0.20,2026-09-02\n"
            "003,01,杯子,-1,0.10,2026-09-02\n"))
        self.data = apply_dataset_mapping(self.state, self.state['commerce_mapping'], 'CNY')['data']
        self.state['commerce_currency_choice'] = 'CNY'

    def test_chart_intent_routes_only_query_mode_and_respects_text_requests(self):
        for request in ['帮我画柱状图', '按商品绘制净销售额柱状图', 'bar chart', 'Plot sales by product', '生成一张折线图']:
            self.assertEqual(resolve_advanced_mode('自然语言查询', request), '自由绘图', request)
        for request in ['计算销售额', '什么是柱状图', '不要画图，只计算总销量', "Don't plot, calculate sales"]:
            self.assertEqual(resolve_advanced_mode('自然语言查询', request), '自然语言查询', request)
        self.assertEqual(resolve_advanced_mode('数据处理', '新增柱状图字段'), '数据处理')

    def test_real_bar_chart_has_correct_amounts_and_keeps_input_and_other_figures(self):
        original = self.data.copy(deep=True)
        other = plt.figure()
        model = ScriptedChatModel(responses=[AIMessage(content=BAR_CODE)])
        try:
            figure, code, error = generate_and_render_chart(model, self.data, '画商品净销售额柱状图')
            self.assertIsNone(error)
            self.assertNotIn('```', code)
            self.assertEqual([round(bar.get_height(), 2) for bar in figure.axes[0].patches], [0.2, 0.2])
            self.assertEqual([tick.get_text() for tick in figure.axes[0].get_xticklabels()], ['01', '02'])
            output = io.BytesIO()
            figure.savefig(output, format='png')
            self.assertGreater(len(output.getvalue()), 5000)
            self.assertTrue(plt.fignum_exists(other.number))
            pd.testing.assert_frame_equal(self.data, original)
            self.assertEqual(len(model.calls), 1)
        finally:
            plt.close(other)

    def test_empty_broken_and_blocked_chart_code_are_errors(self):
        for code, expected in [('fig, ax = plt.subplots()', '没有生成'),
                               ("ax.bar(['A'], [missing])", 'missing'),
                               ("open('example.csv')", 'Unsafe code')]:
            with self.subTest(code=code):
                model = ScriptedChatModel(responses=[AIMessage(content=code)])
                figure, _, error = generate_and_render_chart(model, self.data, '画柱状图')
                self.assertIsNone(figure)
                self.assertIn(expected, error)

    def test_iteration_limit_is_failure_with_real_tool_evidence(self):
        model = ScriptedChatModel(responses=[tool_call('python_repl_ast', {'query': '1+1'}, str(i)) for i in range(4)])
        records = []
        with self.assertRaises(AdvancedQueryError) as caught:
            answer_nlq_text(model, self.data, '计算总数量', tool_calls=records)
        self.assertIn('最多 4 轮', str(caught.exception))
        self.assertNotIn('Agent stopped', str(caught.exception))
        self.assertEqual(len(records), 4)
        self.assertEqual([record['result'] for record in records], [2]*4)
        self.assertEqual(len(model.calls), 4)

    def test_timeout_retains_completed_tools_and_python_errors_are_labelled(self):
        model = ScriptedChatModel(responses=[tool_call('python_repl_ast', {'query': 'missing_name'}),
                                            TimeoutError('test timeout')])
        with self.assertRaises(AdvancedQueryError) as caught:
            answer_nlq_text(model, self.data, '计算数量')
        self.assertIn('test timeout', str(caught.exception))
        self.assertEqual(caught.exception.tool_calls[0]['status'], 'error')
        self.assertIn('NameError', caught.exception.tool_calls[0]['result'])

    def app(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=30)
        for key, value in self.state.items():
            app.session_state[key] = value
        app.run()
        app.toggle(key='commerce_advanced_enabled').set_value(True).run()
        app.text_input(key='model_key_DeepSeek').set_value('test-session-key').run()
        return app

    def test_ui_default_query_routes_to_real_chart_and_displays_it(self):
        app = self.app()
        model = ScriptedChatModel(responses=[AIMessage(content=BAR_CODE)])
        with patch('commerce_ui.create_chat_model', return_value=model):
            app.text_area(key='commerce_advanced_request').set_value('画商品净销售额柱状图').run()
            app.button(key='execute_advanced').click().run()
        self.assertEqual(len(app.exception), 0)
        result = app.session_state['commerce_advanced_result']
        self.assertEqual(result['requested_mode'], '自然语言查询')
        self.assertEqual(result['mode'], '自由绘图')
        self.assertIsNone(result['error'])
        self.assertEqual(len(model.calls), 1)
        self.assertGreater(len(app.image), 0)

    def test_ui_limit_is_error_and_preserves_question_and_tool_records(self):
        app = self.app()
        model = ScriptedChatModel(responses=[tool_call('python_repl_ast', {'query': '1+1'}, str(i)) for i in range(4)])
        with patch('commerce_ui.create_chat_model', return_value=model):
            app.text_area(key='commerce_advanced_request').set_value('计算数量').run()
            app.button(key='execute_advanced').click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('最多 4 轮' in error.value for error in app.error))
        self.assertEqual(app.text_area(key='commerce_advanced_request').value, '计算数量')
        self.assertEqual(len(app.session_state['commerce_advanced_result']['tool_calls']), 4)
        self.assertNotIn('answer', app.session_state['commerce_advanced_result'])


if __name__ == '__main__':
    unittest.main()
