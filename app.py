from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO
import json
import re

import pandas as pd
import streamlit as st

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None
    types = None


st.set_page_config(page_title="不動産投資シミュレーター", page_icon="🏠", layout="wide")


@dataclass
class Inputs:
    purchase_price: float
    sale_price: float
    rent_monthly: float
    vacancy_rate: float
    interest_rate: float
    loan_years: int
    holding_years: int
    down_payment: float
    purchase_cost_rate: float
    sale_cost_rate: float
    management_monthly: float
    repair_monthly: float
    property_city_tax_yearly: float
    property_city_tax_mode: str
    assessment_ratio: float
    management_outsource_rate: float
    restoration_equipment_yearly: float
    building_ratio: float
    useful_life_years: int
    income_tax_rate: float
    capital_gain_tax_rate: float


def yen(value: float) -> str:
    return f"{value:,.0f} 万円"


def calc_monthly_payment(principal: float, annual_rate: float, years: int) -> float:
    months = years * 12
    r = annual_rate / 100 / 12
    if months <= 0:
        return 0.0
    if r == 0:
        return principal / months
    return principal * r * (1 + r) ** months / ((1 + r) ** months - 1)


def estimate_property_city_tax(purchase_price: float, assessment_ratio: float) -> float:
    # 概算：固定資産税1.4% + 都市計画税0.3% = 1.7%
    return purchase_price * assessment_ratio / 100 * 1.7 / 100


def simulate(i: Inputs) -> dict:
    loan_amount = max(i.purchase_price - i.down_payment, 0)
    monthly_payment = calc_monthly_payment(loan_amount, i.interest_rate, i.loan_years)
    building_price = i.purchase_price * i.building_ratio / 100
    land_price = i.purchase_price - building_price
    yearly_depreciation = building_price / i.useful_life_years

    balance = loan_amount
    rows = []
    cumulative_cf = cumulative_tax_effect = cumulative_depreciation = 0.0
    total_interest = total_principal = total_vacancy_loss = total_outsource_fee = 0.0

    for year in range(1, i.holding_years + 1):
        interest_paid = principal_paid = 0.0
        for _ in range(12):
            interest = balance * (i.interest_rate / 100 / 12)
            principal = max(min(monthly_payment - interest, balance), 0)
            balance = max(balance - principal, 0)
            interest_paid += interest
            principal_paid += principal

        gross_rent = i.rent_monthly * 12
        vacancy_loss = gross_rent * i.vacancy_rate / 100
        effective_rent = gross_rent - vacancy_loss
        building_management = i.management_monthly * 12
        repair_reserve = i.repair_monthly * 12
        outsource_fee = effective_rent * i.management_outsource_rate / 100
        running_cost = building_management + repair_reserve + i.property_city_tax_yearly + outsource_fee + i.restoration_equipment_yearly
        loan_payment = interest_paid + principal_paid
        cf_before_tax = effective_rent - running_cost - loan_payment
        taxable_income = effective_rent - running_cost - interest_paid - yearly_depreciation
        tax_effect = -taxable_income * i.income_tax_rate / 100
        cf_after_tax = cf_before_tax + tax_effect

        cumulative_cf += cf_before_tax
        cumulative_tax_effect += tax_effect
        cumulative_depreciation += yearly_depreciation
        total_interest += interest_paid
        total_principal += principal_paid
        total_vacancy_loss += vacancy_loss
        total_outsource_fee += outsource_fee

        rows.append({
            "年": year,
            "満室想定家賃": gross_rent,
            "空室損失": vacancy_loss,
            "実効家賃収入": effective_rent,
            "建物管理費": building_management,
            "修繕積立金": repair_reserve,
            "固定資産税・都市計画税": i.property_city_tax_yearly,
            "管理委託料": outsource_fee,
            "原状回復・設備交換費": i.restoration_equipment_yearly,
            "ローン返済": loan_payment,
            "うち利息": interest_paid,
            "うち元本": principal_paid,
            "減価償却": yearly_depreciation,
            "税務上所得": taxable_income,
            "税効果": tax_effect,
            "税前CF": cf_before_tax,
            "税後CF": cf_after_tax,
            "ローン残債": balance,
        })

    sale_cost = i.sale_price * i.sale_cost_rate / 100
    building_book_value = max(building_price - cumulative_depreciation, 0)
    acquisition_cost = land_price + building_book_value
    capital_gain = i.sale_price - acquisition_cost - sale_cost
    capital_gain_tax = max(capital_gain, 0) * i.capital_gain_tax_rate / 100
    sale_cash_after_tax = i.sale_price - sale_cost - balance - capital_gain_tax
    purchase_cost = i.purchase_price * i.purchase_cost_rate / 100
    initial_cash_out = i.down_payment + purchase_cost
    final_profit = cumulative_cf + cumulative_tax_effect + sale_cash_after_tax - initial_cash_out

    return {
        "rows": pd.DataFrame(rows),
        "loan_amount": loan_amount,
        "monthly_payment": monthly_payment,
        "building_price": building_price,
        "land_price": land_price,
        "yearly_depreciation": yearly_depreciation,
        "cumulative_depreciation": cumulative_depreciation,
        "loan_balance": balance,
        "purchase_cost": purchase_cost,
        "sale_cost": sale_cost,
        "building_book_value": building_book_value,
        "acquisition_cost": acquisition_cost,
        "capital_gain": capital_gain,
        "capital_gain_tax": capital_gain_tax,
        "sale_cash_after_tax": sale_cash_after_tax,
        "cumulative_cf": cumulative_cf,
        "cumulative_tax_effect": cumulative_tax_effect,
        "initial_cash_out": initial_cash_out,
        "final_profit": final_profit,
        "total_interest": total_interest,
        "total_principal": total_principal,
        "total_vacancy_loss": total_vacancy_loss,
        "total_outsource_fee": total_outsource_fee,
    }


def analyze_holding_years(inputs: Inputs, max_years: int) -> pd.DataFrame:
    records = []
    for year in range(1, max_years + 1):
        result = simulate(replace(inputs, holding_years=year))
        records.append({
            "保有年数": year,
            "最終利益": result["final_profit"],
            "運用中CF": result["cumulative_cf"],
            "税効果": result["cumulative_tax_effect"],
            "売却時手残り": result["sale_cash_after_tax"],
            "ローン残債": result["loan_balance"],
            "譲渡所得": result["capital_gain"],
            "譲渡所得税": result["capital_gain_tax"],
        })
    return pd.DataFrame(records)


def _money_values(text: str) -> list[int]:
    return [int(m.group(1).replace(",", "")) for m in re.finditer(r"(?:￥|¥)?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})\s*円", text)]


def extract_pdf_text(uploaded_file) -> str:
    if pdfplumber is None:
        st.error("pdfplumber がインストールされていません。再デプロイしてください。")
        return ""
    pages = []
    with pdfplumber.open(BytesIO(uploaded_file.getvalue())) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            pages.append(f"--- PAGE {idx} ---\n{text}")
    return "\n\n".join(pages)


def parse_pdf_properties_rule(uploaded_file) -> pd.DataFrame:
    text = extract_pdf_text(uploaded_file)
    rows = []
    for page_text in text.split("--- PAGE "):
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        header = lines[1] if lines[0].isdigit() else lines[0]
        m = re.match(r"(.+?)\s+([0-9,]+)$", header)
        if not m:
            continue
        name = m.group(1).strip()
        price = float(m.group(2).replace(",", ""))
        money = _money_values(page_text)
        annual_rent = money[0] / 10000 if len(money) >= 1 else None
        monthly_rent = money[1] / 10000 if len(money) >= 2 else None
        repair = money[2] / 10000 if len(money) >= 3 else None
        management = money[3] / 10000 if len(money) >= 4 else None
        status = next((s for s in ["賃貸中", "サブリース中", "空室"] if s in page_text), "")
        rows.append({
            "物件名": name,
            "価格": price,
            "月額家賃": monthly_rent,
            "年間家賃": annual_rent,
            "修繕積立金/月": repair,
            "建物管理費/月": management,
            "賃貸状態": status,
            "表面利回り%": annual_rent / price * 100 if annual_rent and price else None,
            "抽出方法": "ルール",
            "抽出メモ": "要確認",
        })
    return pd.DataFrame(rows)


def _as_float(value) -> float | None:
    if value in [None, "", "null"]:
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def parse_pdf_properties_ai(uploaded_file) -> pd.DataFrame:
    if genai is None or types is None:
        st.error("google-genai パッケージがありません。requirements.txt反映後に再デプロイしてください。")
        return pd.DataFrame()
    api_key = st.secrets.get("GEMINI_API_KEY", None)
    if not api_key:
        st.error("Streamlit Secrets に GEMINI_API_KEY が見つかりません。")
        return pd.DataFrame()

    text = extract_pdf_text(uploaded_file)
    if not text.strip():
        st.warning("PDFからテキストを抽出できませんでした。画像スキャンPDFの場合、次の版で画像OCR対応が必要です。")
        return pd.DataFrame()

    model = st.secrets.get("GEMINI_MODEL", "gemini-1.5-flash")
    client = genai.Client(api_key=api_key)
    prompt = f"""
あなたは日本の不動産投資資料を読み取る専門アシスタントです。
以下のPDF抽出テキストから、物件ごとに必要項目を抽出してください。
単位は必ず「万円」に統一してください。円表記は10000で割って万円にしてください。
価格が「6,270」のように表示されている場合は「6,270万円」として扱ってください。
管理費と修繕積立金は取り違えないでください。不明な場合は null にしてください。
返答はJSONのみで、余計な文章やMarkdownは不要です。

形式：
{{
  "properties": [
    {{
      "物件名": "",
      "所在地": "",
      "価格": 0,
      "月額家賃": 0,
      "年間家賃": 0,
      "建物管理費/月": 0,
      "修繕積立金/月": 0,
      "賃貸状態": "賃貸中/サブリース中/空室/不明",
      "築年月": "",
      "構造": "",
      "専有面積㎡": 0,
      "駅徒歩": "",
      "抽出メモ": ""
    }}
  ]
}}

PDF抽出テキスト：
{text[:50000]}
"""
    try:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        content = resp.text or "{}"
        data = json.loads(content)
    except Exception as exc:
        st.error("Gemini AI抽出でエラーが発生しました。")
        st.exception(exc)
        return pd.DataFrame()

    rows = []
    for p in data.get("properties", []):
        price = _as_float(p.get("価格"))
        monthly_rent = _as_float(p.get("月額家賃"))
        annual_rent = _as_float(p.get("年間家賃"))
        if annual_rent is None and monthly_rent is not None:
            annual_rent = monthly_rent * 12
        rows.append({
            "物件名": p.get("物件名"),
            "所在地": p.get("所在地"),
            "価格": price,
            "月額家賃": monthly_rent,
            "年間家賃": annual_rent,
            "修繕積立金/月": _as_float(p.get("修繕積立金/月")),
            "建物管理費/月": _as_float(p.get("建物管理費/月")),
            "賃貸状態": p.get("賃貸状態"),
            "築年月": p.get("築年月"),
            "構造": p.get("構造"),
            "専有面積㎡": _as_float(p.get("専有面積㎡")),
            "駅徒歩": p.get("駅徒歩"),
            "表面利回り%": annual_rent / price * 100 if annual_rent and price else None,
            "抽出方法": "Gemini AI",
            "抽出メモ": p.get("抽出メモ", "OK"),
        })
    return pd.DataFrame(rows)


def build_inputs_from_row(row: pd.Series, defaults: dict) -> Inputs:
    price = float(row["価格"])
    return Inputs(
        purchase_price=price,
        sale_price=price * defaults["sale_price_rate"] / 100,
        rent_monthly=float(row["月額家賃"] or 0),
        vacancy_rate=defaults["vacancy_rate"],
        interest_rate=defaults["interest_rate"],
        loan_years=defaults["loan_years"],
        holding_years=defaults["holding_years"],
        down_payment=price * defaults["down_payment_rate"] / 100,
        purchase_cost_rate=defaults["purchase_cost_rate"],
        sale_cost_rate=defaults["sale_cost_rate"],
        management_monthly=float(row.get("建物管理費/月") or 0),
        repair_monthly=float(row.get("修繕積立金/月") or 0),
        property_city_tax_yearly=estimate_property_city_tax(price, defaults["assessment_ratio"]),
        property_city_tax_mode="購入価格から概算",
        assessment_ratio=defaults["assessment_ratio"],
        management_outsource_rate=defaults["management_outsource_rate"],
        restoration_equipment_yearly=defaults["restoration_equipment_yearly"],
        building_ratio=defaults["building_ratio"],
        useful_life_years=defaults["useful_life_years"],
        income_tax_rate=defaults["income_tax_rate"],
        capital_gain_tax_rate=defaults["capital_gain_tax_rate"],
    )


def format_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    text_cols = {"物件名", "所在地", "賃貸状態", "築年月", "構造", "駅徒歩", "抽出方法", "抽出メモ", "年", "保有年数"}
    for col in out.columns:
        if col not in text_cols:
            out[col] = out[col].map(lambda x: "" if pd.isna(x) else f"{x:,.1f}")
    return out


def render_single_property_tab() -> None:
    with st.sidebar:
        st.header("単独物件入力")
        purchase_price = st.number_input("購入価格", 500.0, 30000.0, 3000.0, 100.0)
        sale_price = st.number_input("売却価格", 500.0, 30000.0, 3000.0, 100.0)
        rent_monthly = st.number_input("月額家賃（満室想定）", 1.0, 300.0, 10.0, 1.0)
        vacancy_rate = st.slider("空室率（%）", 0.0, 30.0, 5.0, 0.5)
        down_payment = st.number_input("頭金", 0.0, 30000.0, 0.0, 100.0)
        interest_rate = st.number_input("ローン金利（%）", 0.0, 10.0, 2.0, 0.1)
        loan_years = st.number_input("ローン年数", 1, 50, 35, 1)
        holding_years = st.number_input("保有年数", 1, 50, 5, 1)
        max_analysis_years = st.number_input("最適保有年数分析の上限年数", 1, 50, min(35, int(loan_years)), 1)
        management_monthly = st.number_input("月額建物管理費", 0.0, 100.0, 1.0, 0.5)
        repair_monthly = st.number_input("月額修繕積立金", 0.0, 100.0, 1.0, 0.5)
        assessment_ratio = st.number_input("評価額割合%", 10.0, 100.0, 40.0, 5.0)
        property_city_tax_yearly = estimate_property_city_tax(purchase_price, assessment_ratio)
        management_outsource_rate = st.number_input("管理委託料率%", 0.0, 20.0, 5.0, 0.5)
        restoration_equipment_yearly = st.number_input("原状回復・設備交換費/年", 0.0, 500.0, 10.0, 1.0)
        purchase_cost_rate = st.number_input("購入諸費用率%", 0.0, 20.0, 7.0, 0.5)
        sale_cost_rate = st.number_input("売却諸費用率%", 0.0, 20.0, 4.0, 0.5)
        building_ratio = st.number_input("建物割合%", 0.0, 100.0, 80.0, 5.0)
        useful_life_years = st.number_input("償却年数", 1, 60, 47, 1)
        income_tax_rate = st.number_input("運用中税率%", 0.0, 60.0, 20.0, 1.0)
        capital_gain_tax_rate = st.number_input("譲渡所得税率%", 0.0, 60.0, 20.0, 1.0)

    inputs = Inputs(purchase_price, sale_price, rent_monthly, vacancy_rate, interest_rate, int(loan_years), int(holding_years), down_payment, purchase_cost_rate, sale_cost_rate, management_monthly, repair_monthly, property_city_tax_yearly, "購入価格から概算", assessment_ratio, management_outsource_rate, restoration_equipment_yearly, building_ratio, int(useful_life_years), income_tax_rate, capital_gain_tax_rate)
    r = simulate(inputs)
    cols = st.columns(6)
    cols[0].metric("最終利益", yen(r["final_profit"]))
    cols[1].metric("運用中CF", yen(r["cumulative_cf"]))
    cols[2].metric("空室損失累計", yen(r["total_vacancy_loss"]))
    cols[3].metric("税効果", yen(r["cumulative_tax_effect"]))
    cols[4].metric("売却時手残り", yen(r["sale_cash_after_tax"]))
    cols[5].metric("初期持ち出し", yen(r["initial_cash_out"]))
    st.dataframe(format_df(r["rows"]), use_container_width=True, hide_index=True)
    st.line_chart(r["rows"].set_index("年")[["実効家賃収入", "税前CF", "税後CF", "ローン残債"]])

    st.subheader("最適保有年数分析")
    analysis_df = analyze_holding_years(inputs, int(max_analysis_years))
    best_row = analysis_df.loc[analysis_df["最終利益"].idxmax()]
    b1, b2, b3 = st.columns(3)
    b1.metric("最適保有年数", f"{int(best_row['保有年数'])} 年")
    b2.metric("最大最終利益", yen(best_row["最終利益"]))
    b3.metric("売却時手残り", yen(best_row["売却時手残り"]))
    st.line_chart(analysis_df.set_index("保有年数")[["最終利益", "運用中CF", "売却時手残り", "ローン残債"]])


def render_pdf_compare_tab() -> None:
    st.subheader("PDF自動読み取り・複数物件比較")
    extraction_mode = st.radio("抽出方式", ["Gemini AI抽出", "ルール抽出"], horizontal=True)
    uploaded = st.file_uploader("物件PDFをアップロード", type=["pdf"])
    with st.expander("共通前提", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        defaults = {
            "vacancy_rate": c1.number_input("空室率%", 0.0, 30.0, 10.0, 0.5, key="cmp_vacancy"),
            "interest_rate": c1.number_input("金利%", 0.0, 10.0, 2.0, 0.1, key="cmp_rate"),
            "loan_years": int(c1.number_input("ローン年数", 1, 50, 35, 1, key="cmp_loan_years")),
            "holding_years": int(c2.number_input("保有年数", 1, 50, 5, 1, key="cmp_holding_years")),
            "sale_price_rate": c2.number_input("売却価格 / 購入価格%", 50.0, 150.0, 100.0, 1.0, key="cmp_sale_rate"),
            "down_payment_rate": c2.number_input("頭金率%", 0.0, 100.0, 0.0, 5.0, key="cmp_down_rate"),
            "purchase_cost_rate": c3.number_input("購入諸費用率%", 0.0, 20.0, 7.0, 0.5, key="cmp_purchase_cost"),
            "sale_cost_rate": c3.number_input("売却諸費用率%", 0.0, 20.0, 4.0, 0.5, key="cmp_sale_cost"),
            "assessment_ratio": c3.number_input("評価額割合%", 10.0, 100.0, 40.0, 5.0, key="cmp_assess"),
            "management_outsource_rate": c4.number_input("管理委託料率%", 0.0, 20.0, 5.0, 0.5, key="cmp_outsource"),
            "restoration_equipment_yearly": c4.number_input("原状回復・設備交換費/年", 0.0, 500.0, 10.0, 1.0, key="cmp_repair_cost"),
            "building_ratio": c4.number_input("建物割合%", 0.0, 100.0, 80.0, 5.0, key="cmp_building"),
            "useful_life_years": 47,
            "income_tax_rate": 20.0,
            "capital_gain_tax_rate": 20.0,
        }
    if uploaded is None:
        st.info("PDFをアップロードすると、自動抽出結果とランキングを表示します。")
        return

    with st.spinner("PDFを読み取り中..."):
        extracted = parse_pdf_properties_ai(uploaded) if extraction_mode == "Gemini AI抽出" else parse_pdf_properties_rule(uploaded)
    if extracted.empty:
        st.warning("物件情報を抽出できませんでした。")
        return

    st.markdown("#### 抽出結果（必要に応じて修正してください）")
    edited = st.data_editor(extracted, use_container_width=True, hide_index=True, num_rows="dynamic")

    results = []
    detail_results = {}
    for _, row in edited.dropna(subset=["価格", "月額家賃"]).iterrows():
        inputs = build_inputs_from_row(row, defaults)
        result = simulate(inputs)
        detail_results[row["物件名"]] = result
        results.append({
            "物件名": row["物件名"],
            "価格": inputs.purchase_price,
            "月額家賃": inputs.rent_monthly,
            "修繕積立金/月": inputs.repair_monthly,
            "建物管理費/月": inputs.management_monthly,
            "表面利回り%": row.get("表面利回り%"),
            "最終利益": result["final_profit"],
            "運用中CF": result["cumulative_cf"],
            "税効果": result["cumulative_tax_effect"],
            "売却時手残り": result["sale_cash_after_tax"],
            "空室損失累計": result["total_vacancy_loss"],
            "ローン残債": result["loan_balance"],
            "賃貸状態": row.get("賃貸状態", ""),
        })
    result_df = pd.DataFrame(results).sort_values("最終利益", ascending=False)
    st.markdown("#### 比較ランキング")
    st.dataframe(format_df(result_df), use_container_width=True, hide_index=True)
    st.bar_chart(result_df.set_index("物件名")[["最終利益", "運用中CF", "売却時手残り"]])
    selected = st.selectbox("詳細を見る物件", result_df["物件名"].tolist())
    if selected:
        st.markdown(f"#### {selected} の年次CF")
        st.dataframe(format_df(detail_results[selected]["rows"]), use_container_width=True, hide_index=True)
    st.download_button("比較結果CSVをダウンロード", result_df.to_csv(index=False).encode("utf-8-sig"), file_name="real_estate_comparison.csv", mime="text/csv")


def main() -> None:
    st.title("🏠 不動産投資・税金対策シミュレーター")
    st.caption("単独物件分析と、Gemini AIによるPDF複数物件比較に対応しています。")
    tab_single, tab_pdf = st.tabs(["単独物件分析", "PDF複数物件比較"])
    with tab_single:
        render_single_property_tab()
    with tab_pdf:
        render_pdf_compare_tab()
    st.caption("注意：本アプリは概算シミュレーションです。実際の税務判断は税理士等に確認してください。")


if __name__ == "__main__":
    main()
