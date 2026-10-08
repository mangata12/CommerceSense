"""Exercise real Streamlit reruns without a server or a model API call."""

from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest

from commerce_session import load_dataset
from test_commerce_lifecycle import upload


class CommerceUITests(unittest.TestCase):
    def test_mapping_rerun_and_date_interaction_share_standard_data(self):
        state = {}
        load_dataset(state, upload(
            "订单编号,商品编号,商品名称,数量,单价,日期,备选单价\n"
            "001,01,杯子,3,0.10,2026-09-01,1.00\n"
            "002,02,杯子,1,0.20,2026-09-02,2.00\n"
            "003,01,杯子,-1,0.10,2026-09-02,1.00\n"
        ))
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30)
        for key, value in state.items():
            app.session_state[key] = value
        app.run()
        self.assertEqual(len(app.exception), 0)
        app.selectbox(key="commerce_currency_choice").select("CNY").run()
        next(button for button in app.button if button.label == "应用电商字段映射").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["commerce_standard_df"].iloc[0]["order_id"], "001")
        metrics = next(table.value for table in app.dataframe if list(table.value.columns) == ["指标", "结果"])
        self.assertEqual(metrics.set_index("指标").loc["net_sales", "结果"], "0.4")

        # The no-key page still exposes deterministic metrics. Date interaction
        # reruns the whole app without replacing the standard frame with raw CSV.
        app.date_input(key="commerce_current_period").set_value(("2026-09-02", "2026-09-02")).run()
        self.assertEqual(len(app.exception), 0)
        metrics = next(table.value for table in app.dataframe if list(table.value.columns) == ["指标", "结果"])
        self.assertEqual(metrics.set_index("指标").loc["net_sales", "结果"], "0.1")

        app.session_state["commerce_agent_last_answer"] = "旧答案"
        app.session_state["commerce_report"] = "旧报告"
        app.selectbox(key="commerce_mapping_unit_price").select("备选单价").run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("请先应用当前字段映射" in item.value for item in app.info))
        next(button for button in app.button if button.label == "应用电商字段映射").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(str(app.session_state["commerce_standard_df"].iloc[0]["unit_price"]), "1.00")
        self.assertNotIn("commerce_agent_last_answer", app.session_state)
        self.assertNotIn("commerce_report", app.session_state)


if __name__ == "__main__":
    unittest.main()
