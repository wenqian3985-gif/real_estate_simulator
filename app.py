from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="不動産投資シミュレーター",
    page_icon="🏠",
    layout="wide",
)


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
    property_tax_yearly: float
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


def simulate(i: Inputs) -> dict:
    loan_amount = max(i.purchase_price - i.down_payment, 0)
    monthly_payment = calc_monthly_payment(loan_amount, i.interest_rate, i.loan_years)
    building_price = i.purchase_price * i.building_ratio / 100
    land_price = i.purchase_price - building_price
    yearly_depreciation = building_price / i.useful_life_years

    balance = loan_amount
    rows = []
    cumulative_cf = 0.0
    cumulative_tax_saving = 0.0
    cumulative_depreciation = 0.0
    total_interest = 0.0
    total_principal = 0.0
    total_vacancy_loss = 0.0

    for year in range(1, i.holding_years + 1):
        interest_paid = 0.0
        principal_paid = 0.0
        for _ in range(12):
            interest = balance * (i.interest_rate / 100 / 12)
            principal = min(monthly_payment - interest, balance)
            if principal < 0:
                principal = 0
            balance = max(balance - principal, 0)
            interest_paid += interest
            principal_paid += principal

        gross_rent = i.rent_monthly * 12
        vacancy_loss = gross_rent * i.vacancy_rate / 100
        effective_rent = gross_rent - vacancy_loss
        management = i.management_monthly * 12
        repair = i.repair_monthly * 12
        operating_expenses = management + repair + i.property_tax_yearly
        loan_payment = interest_paid + principal_paid
        cf_before_tax = effective_rent - operating_expenses - loan_payment

        tax_income = effective_rent - operating_expenses - interest_paid - yearly_depreciation
        tax_effect = -tax_income * i.income_tax_rate / 100
        # 税務上赤字なら節税プラス、黒字なら納税マイナス
        cf_after_tax = cf_before_tax + tax_effect

        cumulative_cf += cf_before_tax
        cumulative_tax_saving += tax_effect
        cumulative_depreciation += yearly_depreciation
        total_interest += interest_paid
        total_principal += principal_paid
        total_vacancy_loss += vacancy_loss

        rows.append(
            {
                "年": year,
                "満室想定家賃": gross_rent,
                "空室損失": vacancy_loss,
                "実効家賃収入": effective_rent,
                "管理費・修繕積立金": management + repair,
                "固定資産税等": i.property_tax_yearly,
                "ローン返済": loan_payment,
                "うち利息": interest_paid,
                "うち元本": principal_paid,
                "減価償却": yearly_depreciation,
                "税務上所得": tax_income,
                "税効果": tax_effect,
                "税前CF": cf_before_tax,
                "税後CF": cf_after_tax,
                "ローン残債": balance,
            }
        )

    sale_cost = i.sale_price * i.sale_cost_rate / 100
    building_book_value = max(building_price - cumulative_depreciation, 0)
    acquisition_cost = land_price + building_book_value
    capital_gain = i.sale_price - acquisition_cost - sale_cost
    capital_gain_tax = max(capital_gain, 0) * i.capital_gain_tax_rate / 100
    sale_cash_after_tax = i.sale_price - sale_cost - balance - capital_gain_tax
    purchase_cost = i.purchase_price * i.purchase_cost_rate / 100
    initial_cash_out = i.down_payment + purchase_cost
    final_profit = cumulative_cf + cumulative_tax_saving + sale_cash_after_tax - initial_cash_out

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
        "cumulative_tax_saving": cumulative_tax_saving,
        "initial_cash_out": initial_cash_out,
        "final_profit": final_profit,
        "total_interest": total_interest,
        "total_principal": total_principal,
        "total_vacancy_loss": total_vacancy_loss,
    }


def main() -> None:
    st.title("🏠 不動産投資・税金対策シミュレーター")
    st.caption("減価償却、空室率、運用中CF、譲渡所得、売却時手残り、最終利益を一画面で確認します。単位は万円です。")

    with st.sidebar:
        st.header("入力条件")
        purchase_price = st.number_input("購入価格", 500.0, 20000.0, 3000.0, 100.0)
        sale_price = st.number_input("売却価格", 500.0, 20000.0, 3000.0, 100.0)
        rent_monthly = st.number_input("月額家賃（満室想定）", 1.0, 200.0, 10.0, 1.0)
        vacancy_rate = st.slider("空室率（%）", 0.0, 30.0, 5.0, 0.5)
        down_payment = st.number_input("頭金", 0.0, 20000.0, 0.0, 100.0)
        interest_rate = st.number_input("ローン金利（%）", 0.0, 10.0, 2.2, 0.1)
        loan_years = st.number_input("ローン年数", 1, 50, 35, 1)
        holding_years = st.number_input("保有年数", 1, 50, 5, 1)

        st.divider()
        management_monthly = st.number_input("月額管理費", 0.0, 100.0, 1.0, 0.5)
        repair_monthly = st.number_input("月額修繕積立金", 0.0, 100.0, 1.0, 0.5)
        property_tax_yearly = st.number_input("年間固定資産税等", 0.0, 300.0, 8.0, 1.0)
        purchase_cost_rate = st.number_input("購入諸費用率（%）", 0.0, 20.0, 7.0, 0.5)
        sale_cost_rate = st.number_input("売却諸費用率（%）", 0.0, 20.0, 4.0, 0.5)

        st.divider()
        building_ratio = st.number_input("建物割合（%）", 0.0, 100.0, 80.0, 5.0)
        useful_life_years = st.number_input("償却年数", 1, 60, 47, 1)
        income_tax_rate = st.number_input("運用中の所得税・住民税率（%）", 0.0, 60.0, 20.0, 1.0)
        capital_gain_tax_rate = st.number_input("譲渡所得税率（%）", 0.0, 60.0, 20.0, 1.0)

    inputs = Inputs(
        purchase_price=purchase_price,
        sale_price=sale_price,
        rent_monthly=rent_monthly,
        vacancy_rate=vacancy_rate,
        interest_rate=interest_rate,
        loan_years=int(loan_years),
        holding_years=int(holding_years),
        down_payment=down_payment,
        purchase_cost_rate=purchase_cost_rate,
        sale_cost_rate=sale_cost_rate,
        management_monthly=management_monthly,
        repair_monthly=repair_monthly,
        property_tax_yearly=property_tax_yearly,
        building_ratio=building_ratio,
        useful_life_years=int(useful_life_years),
        income_tax_rate=income_tax_rate,
        capital_gain_tax_rate=capital_gain_tax_rate,
    )
    r = simulate(inputs)

    st.subheader("結論")
    cols = st.columns(6)
    cols[0].metric("最終利益", yen(r["final_profit"]))
    cols[1].metric("運用中CF", yen(r["cumulative_cf"]))
    cols[2].metric("空室損失累計", yen(r["total_vacancy_loss"]))
    cols[3].metric("運用中の税効果", yen(r["cumulative_tax_saving"]))
    cols[4].metric("売却時手残り", yen(r["sale_cash_after_tax"]))
    cols[5].metric("初期持ち出し", yen(r["initial_cash_out"]))

    st.info(
        "最終利益 ＝ 運用中CF ＋ 運用中の税効果 ＋ 売却時手残り − 初期持ち出し。"
        "空室率は満室想定家賃から差し引き、実効家賃収入としてCFと税務上所得に反映しています。"
    )

    st.subheader("計算内訳")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("#### ① 家賃・空室")
        st.write(f"満室想定年間家賃 = {yen(inputs.rent_monthly * 12)}")
        st.write(f"空室率 = {inputs.vacancy_rate:.1f}%")
        st.write(f"年間空室損失 = {yen(inputs.rent_monthly * 12 * inputs.vacancy_rate / 100)}")
        st.write(f"空室損失累計 = {yen(r['total_vacancy_loss'])}")
    with c2:
        st.markdown("#### ② ローン")
        st.write(f"借入額 = {yen(r['loan_amount'])}")
        st.write(f"毎月返済 = {r['monthly_payment']:,.2f} 万円")
        st.write(f"保有期間終了時の残債 = {yen(r['loan_balance'])}")
    with c3:
        st.markdown("#### ③ 減価償却")
        st.write(f"建物価格 = {yen(r['building_price'])}")
        st.write(f"土地価格 = {yen(r['land_price'])}")
        st.write(f"年間減価償却 = {yen(r['yearly_depreciation'])}")
        st.write(f"減価償却累計 = {yen(r['cumulative_depreciation'])}")
    with c4:
        st.markdown("#### ④ 譲渡所得")
        st.write(f"建物簿価 = {yen(r['building_book_value'])}")
        st.write(f"取得費 = 土地簿価 + 建物簿価 = {yen(r['acquisition_cost'])}")
        st.write(f"譲渡所得 = 売却価格 − 取得費 − 売却費用 = {yen(r['capital_gain'])}")
        st.write(f"譲渡所得税 = {yen(r['capital_gain_tax'])}")

    st.subheader("数式")
    st.code(
        f"""
実効家賃収入
= 満室想定家賃 × (1 - 空室率)
= {inputs.rent_monthly * 12:.0f} × (1 - {inputs.vacancy_rate:.1f}%)
= {inputs.rent_monthly * 12 * (1 - inputs.vacancy_rate / 100):.0f} 万円 / 年

最終利益
= 運用中CF + 運用中の税効果 + 売却時手残り - 初期持ち出し
= {r['cumulative_cf']:.0f} + {r['cumulative_tax_saving']:.0f} + {r['sale_cash_after_tax']:.0f} - {r['initial_cash_out']:.0f}
= {r['final_profit']:.0f} 万円

譲渡所得
= 売却価格 - 取得費 - 売却費用
= 売却価格 - (土地簿価 + 建物簿価) - 売却費用
= {inputs.sale_price:.0f} - ({r['land_price']:.0f} + {r['building_book_value']:.0f}) - {r['sale_cost']:.0f}
= {r['capital_gain']:.0f} 万円

建物簿価
= 建物価格 - 減価償却累計
= {r['building_price']:.0f} - {r['cumulative_depreciation']:.0f}
= {r['building_book_value']:.0f} 万円
""",
        language="text",
    )

    st.subheader("年次キャッシュフロー")
    df = r["rows"].copy()
    display_df = df.copy()
    for col in display_df.columns:
        if col != "年":
            display_df[col] = display_df[col].map(lambda x: f"{x:,.0f}")
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.subheader("グラフ")
    chart_df = df.set_index("年")[["実効家賃収入", "空室損失", "税前CF", "税後CF", "ローン残債"]]
    st.line_chart(chart_df)

    st.caption("注意：本アプリは概算シミュレーションです。実際の税務判断は税理士等に確認してください。")


if __name__ == "__main__":
    main()
