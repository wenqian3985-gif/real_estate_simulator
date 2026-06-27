from __future__ import annotations

from dataclasses import dataclass, replace
import re
from io import BytesIO

import pandas as pd
import streamlit as st

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None

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
            principal = min(monthly_payment - interest, balance)
            principal = max(principal, 0)
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


def _to_man_yen(raw: str | None) -> float | None:
    if not raw:
        return None
    return int(raw.replace(",", "")) / 10000


def _money_values(text: str) -> list[int]:
    return [int(m.group(1).replace(",", "")) for m in re.finditer(r"(?:￥|¥)?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})\s*円", text)]


def _normalize_text(text: str) -> str:
    return re.sub(r"[ \t　]+", " ", text.replace("\u00a0", " "))


def _near_value_by_words(words: list[dict], label_patterns: list[str], *, same_line_tol: float = 6.0) -> int | None:
    """Find a yen amount near a label using pdfplumber word coordinates.

    RENOSYのPDFではラベルと金額が左右または上下に並ぶことがあるため、
    extract_textの順番ではなく座標を使って近い金額を拾います。
    """
    amount_words = []
    for w in words:
        txt = w.get("text", "")
        m = re.search(r"(?:￥|¥)?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})\s*円?", txt)
        if m:
            amount_words.append((w, int(m.group(1).replace(",", ""))))

    label_words = [w for w in words if any(re.search(p, w.get("text", "")) for p in label_patterns)]
    candidates: list[tuple[float, int]] = []
    for lw in label_words:
        lx0, lx1 = float(lw["x0"]), float(lw["x1"])
        ly0 = float(lw["top"])
        for aw, value in amount_words:
            ax0 = float(aw["x0"])
            ay0 = float(aw["top"])
            same_line = abs(ay0 - ly0) <= same_line_tol
            right_side = ax0 >= lx1 - 2
            near_below = 0 <= ay0 - ly0 <= 34 and abs(ax0 - lx0) <= 90
            if same_line and right_side:
                candidates.append((abs(ax0 - lx1) + abs(ay0 - ly0), value))
            elif near_below:
                candidates.append((abs(ax0 - lx0) + (ay0 - ly0) * 2, value))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def _extract_by_text_label(text: str, label_patterns: list[str]) -> int | None:
    text = _normalize_text(text)
    joined_labels = "|".join(label_patterns)
    # label ... amount yen の順にあるケース
    m = re.search(rf"(?:{joined_labels})[^\n\r￥¥0-9]{{0,20}}(?:￥|¥)?\s*([0-9]{{1,3}}(?:,[0-9]{{3}})+|[0-9]{{4,}})\s*円", text)
    if m:
        return int(m.group(1).replace(",", ""))
    # amount yen ... label の順にあるケース
    m = re.search(rf"(?:￥|¥)?\s*([0-9]{{1,3}}(?:,[0-9]{{3}})+|[0-9]{{4,}})\s*円[^\n\r]{{0,20}}(?:{joined_labels})", text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def parse_pdf_properties(uploaded_file) -> pd.DataFrame:
    if pdfplumber is None:
        st.error("pdfplumber がインストールされていません。Streamlit Cloudを再デプロイしてください。")
        return pd.DataFrame()

    rows = []
    with pdfplumber.open(BytesIO(uploaded_file.getvalue())) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            words = page.extract_words(x_tolerance=2, y_tolerance=3) or []
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if not lines:
                continue

            first = lines[0]
            m = re.match(r"(.+?)\s+([0-9,]+)$", first)
            if not m:
                continue
            name = m.group(1).strip()
            price = float(m.group(2).replace(",", ""))

            money = _money_values(text)
            annual_rent = money[0] / 10000 if len(money) >= 1 else None
            monthly_rent = money[1] / 10000 if len(money) >= 2 else None

            management_yen = _near_value_by_words(words, [r"管理費", r"建物管理費", r"管理費等"])
            repair_yen = _near_value_by_words(words, [r"修繕積立", r"修繕積立金"])
            if management_yen is None:
                management_yen = _extract_by_text_label(text, [r"管理費", r"建物管理費", r"管理費等"])
            if repair_yen is None:
                repair_yen = _extract_by_text_label(text, [r"修繕積立", r"修繕積立金"])

            # RENOSYの抽出テキストではラベルが落ちることがあるため、残る場合は金額順で補完する。
            # 典型順序：年間家賃 → 月額家賃 → 修繕積立金 → 建物管理費
            if len(money) >= 4:
                likely_repair, likely_management = money[2], money[3]
                if repair_yen is None:
                    repair_yen = likely_repair
                if management_yen is None:
                    management_yen = likely_management

            status = ""
            for key in ["賃貸中", "サブリース中", "空室"]:
                if key in text:
                    status = key
                    break

            gross_yield = annual_rent / price * 100 if annual_rent and price else None
            rows.append({
                "物件名": name,
                "ページ": page_no,
                "価格": price,
                "月額家賃": monthly_rent,
                "年間家賃": annual_rent,
                "修繕積立金/月": _to_man_yen(str(repair_yen)) if repair_yen is not None else None,
                "建物管理費/月": _to_man_yen(str(management_yen)) if management_yen is not None else None,
                "賃貸状態": status,
                "表面利回り%": gross_yield,
                "抽出メモ": "OK" if management_yen is not None and repair_yen is not None else "要確認",
            })
    return pd.DataFrame(rows)


def build_inputs_from_row(row: pd.Series, defaults: dict) -> Inputs:
    price = float(row["価格"])
    rent_monthly = float(row["月額家賃"] or 0)
    management_monthly = float(row["建物管理費/月"] or 0)
    repair_monthly = float(row["修繕積立金/月"] or 0)
    property_tax = estimate_property_city_tax(price, defaults["assessment_ratio"])
    return Inputs(
        purchase_price=price,
        sale_price=price * defaults["sale_price_rate"] / 100,
        rent_monthly=rent_monthly,
        vacancy_rate=defaults["vacancy_rate"],
        interest_rate=defaults["interest_rate"],
        loan_years=defaults["loan_years"],
        holding_years=defaults["holding_years"],
        down_payment=price * defaults["down_payment_rate"] / 100,
        purchase_cost_rate=defaults["purchase_cost_rate"],
        sale_cost_rate=defaults["sale_cost_rate"],
        management_monthly=management_monthly,
        repair_monthly=repair_monthly,
        property_city_tax_yearly=property_tax,
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
    for col in out.columns:
        if col not in {"物件名", "賃貸状態", "抽出メモ", "年", "保有年数", "ページ"}:
            out[col] = out[col].map(lambda x: "" if pd.isna(x) else f"{x:,.1f}")
    return out


def render_single_property_tab() -> None:
    with st.sidebar:
        st.header("① 物件・賃貸条件")
        purchase_price = st.number_input("購入価格", 500.0, 30000.0, 3000.0, 100.0)
        sale_price = st.number_input("売却価格", 500.0, 30000.0, 3000.0, 100.0)
        rent_monthly = st.number_input("月額家賃（満室想定）", 1.0, 300.0, 10.0, 1.0)
        vacancy_rate = st.slider("空室率（%）", 0.0, 30.0, 5.0, 0.5)
        st.header("② 融資")
        down_payment = st.number_input("頭金", 0.0, 30000.0, 0.0, 100.0)
        interest_rate = st.number_input("ローン金利（%）", 0.0, 10.0, 2.0, 0.1)
        loan_years = st.number_input("ローン年数", 1, 50, 35, 1)
        holding_years = st.number_input("保有年数", 1, 50, 5, 1)
        max_analysis_years = st.number_input("最適保有年数分析の上限年数", 1, 50, min(35, int(loan_years)), 1)
        st.header("③ ランニングコスト")
        management_monthly = st.number_input("月額建物管理費", 0.0, 100.0, 1.0, 0.5)
        repair_monthly = st.number_input("月額修繕積立金", 0.0, 100.0, 1.0, 0.5)
        assessment_ratio = st.number_input("評価額割合（概算用、購入価格に対する%）", 10.0, 100.0, 40.0, 5.0)
        property_city_tax_yearly = estimate_property_city_tax(purchase_price, assessment_ratio)
        st.caption(f"固定資産税・都市計画税 概算：{yen(property_city_tax_yearly)} / 年")
        management_outsource_rate = st.number_input("管理委託料率（実効家賃に対する%）", 0.0, 20.0, 5.0, 0.5)
        restoration_equipment_yearly = st.number_input("年間 原状回復・設備交換費", 0.0, 500.0, 10.0, 1.0)
        st.header("④ 税金・諸費用")
        purchase_cost_rate = st.number_input("購入諸費用率（%）", 0.0, 20.0, 7.0, 0.5)
        sale_cost_rate = st.number_input("売却諸費用率（%）", 0.0, 20.0, 4.0, 0.5)
        building_ratio = st.number_input("建物割合（%）", 0.0, 100.0, 80.0, 5.0)
        useful_life_years = st.number_input("償却年数", 1, 60, 47, 1)
        income_tax_rate = st.number_input("運用中の所得税・住民税率（%）", 0.0, 60.0, 20.0, 1.0)
        capital_gain_tax_rate = st.number_input("譲渡所得税率（%）", 0.0, 60.0, 20.0, 1.0)

    inputs = Inputs(purchase_price, sale_price, rent_monthly, vacancy_rate, interest_rate, int(loan_years), int(holding_years), down_payment, purchase_cost_rate, sale_cost_rate, management_monthly, repair_monthly, property_city_tax_yearly, "購入価格から概算", assessment_ratio, management_outsource_rate, restoration_equipment_yearly, building_ratio, int(useful_life_years), income_tax_rate, capital_gain_tax_rate)
    r = simulate(inputs)
    st.subheader("結論")
    cols = st.columns(6)
    cols[0].metric("最終利益", yen(r["final_profit"]))
    cols[1].metric("運用中CF", yen(r["cumulative_cf"]))
    cols[2].metric("空室損失累計", yen(r["total_vacancy_loss"]))
    cols[3].metric("税効果", yen(r["cumulative_tax_effect"]))
    cols[4].metric("売却時手残り", yen(r["sale_cash_after_tax"]))
    cols[5].metric("初期持ち出し", yen(r["initial_cash_out"]))
    st.info("最終利益 ＝ 運用中CF ＋ 運用中の税効果 ＋ 売却時手残り − 初期持ち出し")
    st.subheader("年次キャッシュフロー")
    st.dataframe(format_df(r["rows"]), use_container_width=True, hide_index=True)
    st.line_chart(r["rows"].set_index("年")[["実効家賃収入", "税前CF", "税後CF", "ローン残債"]])
    st.subheader("最適保有年数分析")
    analysis_df = analyze_holding_years(inputs, int(max_analysis_years))
    best_row = analysis_df.loc[analysis_df["最終利益"].idxmax()]
    b1, b2, b3 = st.columns(3)
    b1.metric("最終利益が最大の保有年数", f"{int(best_row['保有年数'])} 年")
    b2.metric("最大最終利益", yen(best_row["最終利益"]))
    b3.metric("その時の売却時手残り", yen(best_row["売却時手残り"]))
    st.line_chart(analysis_df.set_index("保有年数")[["最終利益", "運用中CF", "売却時手残り", "ローン残債"]])


def render_pdf_compare_tab() -> None:
    st.subheader("PDF自動読み取り・複数物件比較")
    st.caption("文字データを含むPDFに対応します。管理費・修繕積立金はラベル近傍の金額を優先して抽出します。")
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
    extracted = parse_pdf_properties(uploaded)
    if extracted.empty:
        st.warning("物件情報を抽出できませんでした。PDFが画像のみの場合は未対応です。")
        return
    st.markdown("#### 抽出結果")
    st.caption("抽出メモが『要確認』の行は、管理費・修繕積立金などを手修正してください。")
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
    st.caption("単独物件分析と、PDF自動読み取りによる複数物件比較に対応しています。")
    tab_single, tab_pdf = st.tabs(["単独物件分析", "PDF複数物件比較"])
    with tab_single:
        render_single_property_tab()
    with tab_pdf:
        render_pdf_compare_tab()
    st.caption("注意：本アプリは概算シミュレーションです。実際の税務判断は税理士等に確認してください。")


if __name__ == "__main__":
    main()
