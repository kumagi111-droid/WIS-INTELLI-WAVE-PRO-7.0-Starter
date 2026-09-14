import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, date, timedelta

# =========================================================
# WIS INTELLI-WAVE PRO v7.1
# Modern UI + Daily Operation + Quarterly Laboratory
# PostgreSQL / Supabase cloud database
# =========================================================

st.set_page_config(
    page_title="WIS INTELLI-WAVE PRO v7.1",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_LABEL = "Supabase PostgreSQL"

# -----------------------------
# CLOUD DATABASE (SUPABASE / POSTGRESQL)
# -----------------------------
def get_conn():
    """Create a secure PostgreSQL connection using Streamlit Secrets."""
    if "DATABASE_URL" not in st.secrets:
        raise RuntimeError("DATABASE_URL is not configured in Streamlit Secrets")
    return psycopg2.connect(st.secrets["DATABASE_URL"], sslmode="require")

def test_db_connection():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        conn.close()
        return True, None
    except Exception as e:
        return False, str(e)

def query_dataframe(sql_text):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql_text)
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description]
        return pd.DataFrame(rows, columns=columns)
    finally:
        conn.close()

def load_operations(limit=None):
    sql_text = "SELECT * FROM operation_records ORDER BY record_date DESC, record_time DESC NULLS LAST, id DESC"
    if limit:
        sql_text += f" LIMIT {int(limit)}"
    return query_dataframe(sql_text)

def load_labs(limit=None):
    sql_text = "SELECT * FROM laboratory_records ORDER BY sample_date DESC, id DESC"
    if limit:
        sql_text += f" LIMIT {int(limit)}"
    return query_dataframe(sql_text)

def insert_record(table_name, data):
    allowed_tables = {"operation_records", "laboratory_records", "audit_log"}
    if table_name not in allowed_tables:
        raise ValueError("Invalid table name")

    columns = list(data.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    column_sql = ", ".join(columns)
    sql_text = f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})"

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql_text, tuple(data[c] for c in columns))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def save_operation(data):
    insert_record("operation_records", data)

def save_lab(data):
    insert_record("laboratory_records", data)

DB_CONNECTED, DB_ERROR = test_db_connection()

# -----------------------------
# ENGINEERING CALCULATIONS
# -----------------------------
def calc_metrics(flow_in, bod_in, do_aer, sv30, mlss, energy_kwh, design_flow, aeration_volume):
    svi = (sv30 * 1000 / mlss) if mlss and mlss > 0 else None
    fm = (flow_in * bod_in / (aeration_volume * mlss)) if all(
        [flow_in and flow_in > 0, bod_in and bod_in > 0, aeration_volume and aeration_volume > 0, mlss and mlss > 0]
    ) else None
    hrt = (aeration_volume / flow_in * 24) if flow_in and flow_in > 0 else None
    hydraulic = (flow_in / design_flow * 100) if design_flow and design_flow > 0 else None
    sec = (energy_kwh / flow_in) if flow_in and flow_in > 0 else None
    return svi, fm, hrt, hydraulic, sec

def classify_process(ph_aer, do_aer, mlss, svi, fm_ratio, hydraulic_load, hrt):
    alerts = []

    def add(level, title, detail):
        alerts.append({"level": level, "title": title, "detail": detail})

    if ph_aer is not None:
        if ph_aer < 6.0 or ph_aer > 9.0:
            add("CRITICAL", "pH นอกช่วงรุนแรง", "ตรวจสอบแหล่งน้ำเข้าและสภาวะถังเติมอากาศทันที")
        elif ph_aer < 6.5 or ph_aer > 8.5:
            add("WATCH", "pH ใกล้ขอบเขตควบคุม", "ติดตามแนวโน้มและตรวจสอบสาเหตุ")

    if do_aer is not None:
        if do_aer < 1.0:
            add("CRITICAL", "DO ต่ำมาก", "ตรวจ Blower, diffuser, loading และตะกอนในระบบ")
        elif do_aer < 1.5:
            add("WARNING", "DO ต่ำ", "เพิ่มการเติมอากาศและตรวจภาระสารอินทรีย์")
        elif do_aer > 4.0:
            add("WATCH", "DO สูง", "ประเมินการใช้พลังงานและปรับ aeration ตามความเหมาะสม")

    if mlss is not None:
        if mlss < 1500:
            add("WARNING", "MLSS ต่ำ", "ตรวจการสูญเสียตะกอนและการควบคุม sludge age")
        elif mlss > 5000:
            add("WARNING", "MLSS สูง", "พิจารณาการระบายตะกอนส่วนเกินตามสภาพระบบ")

    if svi is not None:
        if svi > 180:
            add("CRITICAL", "SVI สูงมาก", "เสี่ยง bulking ควรตรวจ settling, filamentous และ RAS/WAS")
        elif svi > 150:
            add("WARNING", "SVI สูง", "ติดตามการตกตะกอนและคุณภาพ sludge")
        elif svi < 60:
            add("WATCH", "SVI ต่ำ", "ตรวจ pin floc / old sludge / settling characteristics")

    if fm_ratio is not None:
        if fm_ratio < 0.03:
            add("WATCH", "F/M ต่ำ", "อาจสัมพันธ์กับ sludge age สูง ตรวจภาระอินทรีย์และ WAS")
        elif fm_ratio > 0.25:
            add("WARNING", "F/M สูง", "ตรวจ organic loading และความสามารถในการเติมอากาศ")

    if hydraulic_load is not None:
        if hydraulic_load > 120:
            add("CRITICAL", "Hydraulic Load สูงมาก", "ตรวจ peak flow, bypass, infiltration/inflow")
        elif hydraulic_load > 100:
            add("WARNING", "Hydraulic Load เกิน Design", "เฝ้าระวัง HRT และคุณภาพน้ำทิ้ง")

    if hrt is not None and hrt < 4:
        add("WARNING", "HRT ต่ำ", "ประเมินอัตราการไหลเทียบกับปริมาตรถัง")

    rank = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}
    overall = "NORMAL"
    for a in alerts:
        if rank[a["level"]] > rank[overall]:
            overall = a["level"]

    return overall, alerts

# -----------------------------
# UI HELPERS
# -----------------------------
STATUS_CLASS = {
    "NORMAL": ("status-normal", "●"),
    "WATCH": ("status-watch", "●"),
    "WARNING": ("status-warning", "●"),
    "CRITICAL": ("status-critical", "●"),
}

def metric_card(title, value, unit="", status="NORMAL", icon="💧", sub=""):
    status_class, dot = STATUS_CLASS.get(status, STATUS_CLASS["NORMAL"])
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-top">
                <div class="metric-icon">{icon}</div>
                <div class="metric-label">{title}</div>
            </div>
            <div class="metric-value">{value}<span class="metric-unit"> {unit}</span></div>
            <div class="{status_class}">{dot} {status.title()}</div>
            <div class="metric-sub">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

def section_title(icon, title, right_text=""):
    st.markdown(
        f"""
        <div class="section-head">
            <div class="section-title">{icon} {title}</div>
            <div class="section-right">{right_text}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

def alert_box(level, title, detail):
    css = {
        "NORMAL": "alert-normal",
        "WATCH": "alert-watch",
        "WARNING": "alert-warning",
        "CRITICAL": "alert-critical"
    }.get(level, "alert-normal")
    st.markdown(
        f"""
        <div class="alert-box {css}">
            <b>{level}: {title}</b><br>
            <span>{detail}</span>
        </div>
        """,
        unsafe_allow_html=True
    )

# -----------------------------
# CSS
# -----------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Sarabun', sans-serif;
}

.stApp {
    background: #f4f8fb;
}

[data-testid="stHeader"] {
    background: rgba(255,255,255,0.92);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid #e7eef5;
}

.block-container {
    padding-top: 2.3rem !important;
    padding-bottom: 3rem !important;
    max-width: 1600px;
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #ffffff 0%, #f5f9fd 100%);
    border-right: 1px solid #e1eaf2;
}

[data-testid="stSidebar"] > div:first-child {
    padding-top: 1.2rem;
}

.brand {
    background: linear-gradient(135deg, #0d57a8 0%, #1686c9 55%, #27ae60 100%);
    padding: 18px 18px;
    border-radius: 18px;
    color: white;
    margin-bottom: 18px;
    box-shadow: 0 8px 24px rgba(15, 88, 164, .18);
}
.brand-title {
    font-size: 1.30rem;
    font-weight: 700;
    letter-spacing: .2px;
}
.brand-sub {
    font-size: .78rem;
    opacity: .9;
    margin-top: 4px;
}

.hero {
    position: relative;
    overflow: hidden;
    border-radius: 22px;
    padding: 24px 28px;
    background:
        radial-gradient(circle at 87% 24%, rgba(33,150,243,.17), transparent 24%),
        radial-gradient(circle at 72% 100%, rgba(39,174,96,.13), transparent 30%),
        linear-gradient(135deg, #ffffff 0%, #f5fbff 65%, #eefaf4 100%);
    border: 1px solid #dceaf5;
    box-shadow: 0 10px 30px rgba(39,79,112,.08);
    margin-bottom: 18px;
}
.hero-kicker {
    font-size: .85rem;
    font-weight: 700;
    letter-spacing: 1.5px;
    color: #1686c9;
    text-transform: uppercase;
}
.hero-title {
    color: #103b66;
    font-weight: 700;
    font-size: clamp(2rem, 3.3vw, 3.25rem);
    line-height: 1.08;
    margin-top: 6px;
}
.hero-sub {
    color: #587188;
    font-size: 1.05rem;
    margin-top: 6px;
}
.hero-badge {
    display: inline-block;
    margin-top: 14px;
    background: #e9f8f0;
    color: #168a55;
    border: 1px solid #caeedb;
    border-radius: 999px;
    padding: 6px 12px;
    font-weight: 600;
    font-size: .84rem;
}

.metric-card {
    min-height: 180px;
    background: #ffffff;
    border: 1px solid #e0eaf2;
    border-radius: 18px;
    padding: 18px 18px 16px 18px;
    box-shadow: 0 8px 24px rgba(34,72,102,.07);
    transition: transform .18s ease, box-shadow .18s ease;
}
.metric-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 12px 28px rgba(34,72,102,.12);
}
.metric-top {
    display:flex;
    align-items:center;
    gap:10px;
}
.metric-icon {
    width: 40px;
    height: 40px;
    border-radius: 12px;
    display:flex;
    align-items:center;
    justify-content:center;
    background:#eef7ff;
    font-size: 1.25rem;
}
.metric-label {
    color:#536a7c;
    font-weight:600;
    font-size:.92rem;
}
.metric-value {
    color:#102a43;
    font-size:2rem;
    font-weight:700;
    margin-top:12px;
    line-height:1.1;
}
.metric-unit {
    font-size:.82rem;
    color:#708090;
    font-weight:500;
}
.metric-sub {
    margin-top:7px;
    color:#8493a0;
    font-size:.78rem;
}
.status-normal, .status-watch, .status-warning, .status-critical {
    display:inline-block;
    padding:4px 9px;
    border-radius:999px;
    margin-top:10px;
    font-size:.77rem;
    font-weight:700;
}
.status-normal {background:#e8f8ef;color:#168a55;}
.status-watch {background:#fff7df;color:#a66a00;}
.status-warning {background:#fff0dc;color:#c56a00;}
.status-critical {background:#ffebeb;color:#c93e3e;}

.section-head {
    display:flex;
    justify-content:space-between;
    align-items:center;
    margin: 8px 0 10px 0;
}
.section-title {
    color:#123f6a;
    font-size:1.08rem;
    font-weight:700;
}
.section-right {
    color:#7b8c9a;
    font-size:.82rem;
}

.panel {
    background:white;
    border:1px solid #e0eaf2;
    border-radius:18px;
    padding:18px;
    box-shadow:0 8px 24px rgba(34,72,102,.06);
    margin-bottom:14px;
}

.process-flow {
    display:grid;
    grid-template-columns: repeat(6, 1fr);
    gap:10px;
}
.process-node {
    background:linear-gradient(180deg,#f7fbff,#eef6fc);
    border:1px solid #ddeaf4;
    border-radius:14px;
    padding:14px 8px;
    text-align:center;
    min-height:110px;
}
.process-icon {font-size:1.55rem;}
.process-name {font-weight:700;color:#193d5f;font-size:.85rem;margin-top:7px;}
.process-data {color:#678096;font-size:.78rem;margin-top:5px;}

.alert-box {
    border-radius:12px;
    padding:12px 14px;
    margin-bottom:8px;
    border-left:4px solid;
    font-size:.88rem;
}
.alert-normal {background:#eefaf4;border-color:#2eaf70;color:#225c3f;}
.alert-watch {background:#fff9e9;border-color:#e6a700;color:#745600;}
.alert-warning {background:#fff4e6;border-color:#f08c2e;color:#814b13;}
.alert-critical {background:#fff0f0;border-color:#d84a4a;color:#7c2727;}

.small-note {
    color:#80909d;
    font-size:.78rem;
}

div[data-baseweb="tab-list"] {
    gap: 6px;
}
button[data-baseweb="tab"] {
    background: white;
    border-radius: 10px;
    border: 1px solid #e0eaf2;
    padding-left: 14px;
    padding-right: 14px;
}

@media (max-width: 1000px) {
    .process-flow {grid-template-columns: repeat(2, 1fr);}
}
</style>
""", unsafe_allow_html=True)

# -----------------------------
# SIDEBAR
# -----------------------------
with st.sidebar:
    st.markdown("""
    <div class="brand">
        <div class="brand-title">💧 WIS INTELLI-WAVE PRO</div>
        <div class="brand-sub">Hospital Wastewater Management System · v7.1</div>
    </div>
    """, unsafe_allow_html=True)

    page = st.radio(
        "เมนูหลัก",
        [
            "🏠 Dashboard",
            "📝 Daily Operation",
            "🧪 Laboratory (Quarterly)",
            "📊 Process Analysis",
            "📈 Historical Data",
            "🛡️ Standards & Compliance",
            "📄 Reports",
            "⚙️ Settings",
        ],
        label_visibility="collapsed"
    )

    st.divider()
    st.caption("Plant Configuration")
    design_flow = st.number_input("Design Flow (m³/day)", min_value=1.0, value=98.0, step=1.0)
    aeration_volume = st.number_input("Aeration Volume (m³)", min_value=1.0, value=60.0, step=1.0)

    st.divider()
    if DB_CONNECTED:
        st.success("● Cloud Database Connected")
        st.caption("Supabase PostgreSQL · Secure connection")
    else:
        st.error("● Database Connection Error")
        st.caption("ตรวจสอบ Streamlit Secrets / DATABASE_URL")

# -----------------------------
# LOAD DATA
# -----------------------------
if DB_CONNECTED:
    try:
        ops = load_operations()
        labs = load_labs()
    except Exception as e:
        st.error(f"ไม่สามารถอ่านข้อมูลจาก Cloud Database ได้: {e}")
        ops = pd.DataFrame()
        labs = pd.DataFrame()
else:
    ops = pd.DataFrame()
    labs = pd.DataFrame()

latest_op = ops.iloc[0].to_dict() if not ops.empty else {}
latest_lab = labs.iloc[0].to_dict() if not labs.empty else {}

# -----------------------------
# HERO
# -----------------------------
st.markdown("""
<div class="hero">
    <div class="hero-kicker">Wastewater Intelligence System</div>
    <div class="hero-title">WIS INTELLI-WAVE PRO</div>
    <div class="hero-sub">ระบบวิเคราะห์ เฝ้าระวัง และสนับสนุนการตัดสินใจสำหรับระบบบำบัดน้ำเสียโรงพยาบาล</div>
    <div class="hero-badge">● Smart Monitoring · Process Diagnosis · Compliance Review</div>
</div>
""", unsafe_allow_html=True)

# =========================================================
# DASHBOARD
# =========================================================
if page == "🏠 Dashboard":
    flow = latest_op.get("flow_in", 0) or 0
    do = latest_op.get("do_aer", 0) or 0
    sv30 = latest_op.get("sv30", 0) or 0
    mlss = latest_op.get("mlss", 0) or 0
    overall = latest_op.get("overall_status", "NORMAL") or "NORMAL"

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        metric_card("Flow (Inlet)", f"{flow:,.0f}", "m³/day", "NORMAL", "💧", "Daily Operation")
    with c2:
        do_status = "CRITICAL" if do and do < 1 else "WARNING" if do and do < 1.5 else "NORMAL"
        metric_card("DO (Aeration)", f"{do:,.1f}", "mg/L", do_status, "🎯", "Aeration Tank")
    with c3:
        sv_status = "CRITICAL" if sv30 and sv30 > 500 else "WATCH" if sv30 and sv30 > 350 else "NORMAL"
        metric_card("SV30", f"{sv30:,.0f}", "mL/L", sv_status, "🧪", "Settling Observation")
    with c4:
        metric_card("MLSS", f"{mlss:,.0f}", "mg/L", "NORMAL", "🌡️", "Measured / Entered")
    with c5:
        metric_card("Overall Status", overall, "", overall, "🛡️", "Process Condition")

    st.write("")

    left, right = st.columns([1.35, 1])

    with left:
        section_title("🌊", "Process Overview", "Current process snapshot")
        st.markdown(f"""
        <div class="panel">
            <div class="process-flow">
                <div class="process-node">
                    <div class="process-icon">🚰</div>
                    <div class="process-name">Influent</div>
                    <div class="process-data">{flow:,.0f} m³/d</div>
                </div>
                <div class="process-node">
                    <div class="process-icon">⚖️</div>
                    <div class="process-name">Equalization</div>
                    <div class="process-data">Flow balancing</div>
                </div>
                <div class="process-node">
                    <div class="process-icon">💨</div>
                    <div class="process-name">Aeration</div>
                    <div class="process-data">DO {do:,.1f} mg/L</div>
                </div>
                <div class="process-node">
                    <div class="process-icon">🫧</div>
                    <div class="process-name">Clarifier</div>
                    <div class="process-data">SV30 {sv30:,.0f} mL/L</div>
                </div>
                <div class="process-node">
                    <div class="process-icon">🧴</div>
                    <div class="process-name">Disinfection</div>
                    <div class="process-data">Chlorine control</div>
                </div>
                <div class="process-node">
                    <div class="process-icon">🌊</div>
                    <div class="process-name">Effluent</div>
                    <div class="process-data">Discharge</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        section_title("📈", "Trends", "Last 14 records")
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        if not ops.empty:
            chart_df = ops.head(14).copy()
            chart_df["record_date"] = pd.to_datetime(chart_df["record_date"])
            chart_df = chart_df.sort_values("record_date").set_index("record_date")
            trend_choice = st.segmented_control(
                "Trend parameter",
                ["DO", "SV30", "MLSS", "Flow"],
                default="MLSS",
                label_visibility="collapsed"
            )
            col_map = {"DO":"do_aer", "SV30":"sv30", "MLSS":"mlss", "Flow":"flow_in"}
            st.line_chart(chart_df[[col_map[trend_choice]]], height=260)
        else:
            st.info("ยังไม่มีข้อมูล Daily Operation")
        st.markdown('</div>', unsafe_allow_html=True)

    with right:
        section_title("🧪", "Latest Laboratory Result", "Quarterly / periodic result")
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        if latest_lab:
            st.caption(f"Sample date: {latest_lab.get('sample_date','-')}")
            lab_view = pd.DataFrame({
                "Parameter": ["BOD", "COD", "SS", "TKN", "Fecal Coliform"],
                "Result": [
                    latest_lab.get("bod"),
                    latest_lab.get("cod"),
                    latest_lab.get("ss"),
                    latest_lab.get("tkn"),
                    latest_lab.get("fecal_coliform"),
                ],
                "Unit": ["mg/L", "mg/L", "mg/L", "mg/L", "MPN/100 mL"]
            })
            st.dataframe(lab_view, use_container_width=True, hide_index=True)
        else:
            st.info("ยังไม่มีผล Laboratory ในฐานข้อมูล")
        st.markdown('</div>', unsafe_allow_html=True)

        section_title("🛡️", "Compliance Snapshot", "Reference view")
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.write("ระบบจะแยกผล **Lab** ออกจากข้อมูลเดินระบบประจำวัน")
        st.caption("ค่ามาตรฐานด้านล่างเป็นพื้นที่สำหรับตั้งค่าให้ตรงกับกฎหมาย/ใบอนุญาต/เกณฑ์ของโรงพยาบาลที่ใช้จริง")
        st.markdown("✅ BOD  ·  ✅ COD  ·  ✅ SS  ·  ✅ TKN")
        st.markdown('</div>', unsafe_allow_html=True)

    st.write("")
    a1, a2, a3 = st.columns([1.6, 1, 1])

    with a1:
        section_title("💡", "Alerts & Recommendations")
        st.markdown('<div class="panel">', unsafe_allow_html=True)

        if latest_op:
            _, alerts = classify_process(
                latest_op.get("ph_aer"),
                latest_op.get("do_aer"),
                latest_op.get("mlss"),
                latest_op.get("svi"),
                latest_op.get("fm_ratio"),
                latest_op.get("hydraulic_load"),
                latest_op.get("hrt")
            )
            if alerts:
                for item in alerts[:4]:
                    alert_box(item["level"], item["title"], item["detail"])
            else:
                alert_box("NORMAL", "ระบบโดยรวม", "ยังไม่พบเงื่อนไขแจ้งเตือนจากข้อมูลล่าสุด")
        else:
            st.info("บันทึก Daily Operation เพื่อเริ่มวิเคราะห์")
        st.markdown('</div>', unsafe_allow_html=True)

    with a2:
        section_title("📅", "Next Laboratory Due")
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        if latest_lab and latest_lab.get("sample_date"):
            next_due = pd.to_datetime(latest_lab["sample_date"]).date() + timedelta(days=90)
            st.metric("Next sample", next_due.strftime("%d %b %Y"))
        else:
            st.metric("Next sample", "Not set")
        st.caption("ปรับช่วงรอบตรวจได้ใน Settings")
        st.markdown('</div>', unsafe_allow_html=True)

    with a3:
        section_title("⚡", "Quick Actions")
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.write("• บันทึกข้อมูลวันนี้")
        st.write("• เพิ่มผล Lab")
        st.write("• ตรวจประวัติย้อนหลัง")
        st.markdown('</div>', unsafe_allow_html=True)

# =========================================================
# DAILY OPERATION
# =========================================================
elif page == "📝 Daily Operation":
    st.subheader("📝 Daily Operation")
    st.caption("ข้อมูลควบคุมระบบประจำวัน แยกจากผล Laboratory")

    with st.form("daily_form"):
        top1, top2, top3 = st.columns(3)
        with top1:
            record_date = st.date_input("วันที่", value=date.today())
        with top2:
            record_time = st.time_input("เวลา", value=datetime.now().time().replace(second=0, microsecond=0))
        with top3:
            operator = st.text_input("ผู้บันทึก", value="")

        st.markdown("#### Hydraulic & Energy")
        c1, c2, c3 = st.columns(3)
        with c1:
            flow_in = st.number_input("Flow In (m³/day)", min_value=0.0, value=0.0)
            flow_out = st.number_input("Flow Out (m³/day)", min_value=0.0, value=0.0)
        with c2:
            energy_kwh = st.number_input("Energy (kWh/day)", min_value=0.0, value=0.0)
            chlorine_out = st.number_input("Residual Chlorine (mg/L)", min_value=0.0, value=0.0)
        with c3:
            bod_in = st.number_input("BOD In for F/M (mg/L) - ถ้ามี", min_value=0.0, value=0.0)
            note = st.text_area("หมายเหตุ", height=92)

        st.markdown("#### Biological Process")
        c4, c5, c6 = st.columns(3)
        with c4:
            do_aer = st.number_input("DO Aeration (mg/L)", min_value=0.0, value=2.0)
            sv30 = st.number_input("SV30 (mL/L)", min_value=0.0, max_value=1000.0, value=300.0)
        with c5:
            mlss = st.number_input("MLSS (mg/L)", min_value=0.0, value=3000.0)
            ph_aer = st.number_input("pH Aeration", min_value=0.0, max_value=14.0, value=7.0)
        with c6:
            ph_in = st.number_input("pH Inlet", min_value=0.0, max_value=14.0, value=7.0)
            ph_out = st.number_input("pH Effluent (Field)", min_value=0.0, max_value=14.0, value=7.0)

        svi, fm, hrt, hydraulic, sec = calc_metrics(
            flow_in, bod_in, do_aer, sv30, mlss, energy_kwh, design_flow, aeration_volume
        )
        overall, alerts = classify_process(ph_aer, do_aer, mlss, svi, fm, hydraulic, hrt)

        st.markdown("#### Auto Calculation")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("SVI", "-" if svi is None else f"{svi:.1f} mL/g")
        m2.metric("F/M", "-" if fm is None else f"{fm:.3f}")
        m3.metric("HRT", "-" if hrt is None else f"{hrt:.1f} hr")
        m4.metric("Hydraulic Load", "-" if hydraulic is None else f"{hydraulic:.1f}%")
        m5.metric("SEC", "-" if sec is None else f"{sec:.2f} kWh/m³")

        submitted = st.form_submit_button("💾 Save & Analyze", use_container_width=True)

    if submitted:
        if not DB_CONNECTED:
            st.error("ยังไม่สามารถบันทึกได้ เพราะ Cloud Database ยังไม่เชื่อมต่อ")
            st.stop()
        save_operation({
            "record_date": record_date.isoformat(),
            "record_time": record_time.strftime("%H:%M"),
            "operator": operator,
            "flow_in": flow_in,
            "flow_out": flow_out,
            "ph_in": ph_in,
            "ph_aer": ph_aer,
            "ph_out": ph_out,
            "do_aer": do_aer,
            "sv30": sv30,
            "mlss": mlss,
            "chlorine_out": chlorine_out,
            "energy_kwh": energy_kwh,
            "svi": svi,
            "fm_ratio": fm,
            "hrt": hrt,
            "hydraulic_load": hydraulic,
            "sec": sec,
            "overall_status": overall,
            "note": note,
            "created_at": datetime.now().isoformat(timespec="seconds")
        })
        st.success(f"บันทึกสำเร็จ · Overall Status = {overall}")
        for item in alerts:
            alert_box(item["level"], item["title"], item["detail"])

# =========================================================
# LABORATORY
# =========================================================
elif page == "🧪 Laboratory (Quarterly)":
    st.subheader("🧪 Laboratory (Quarterly / Periodic)")
    st.caption("สำหรับผลตรวจห้องปฏิบัติการตามรอบ ไม่ใช่ข้อมูลประจำวัน")

    with st.form("lab_form"):
        r1, r2, r3 = st.columns(3)
        with r1:
            sample_date = st.date_input("วันที่เก็บตัวอย่าง", value=date.today())
        with r2:
            report_date = st.date_input("วันที่ออกรายงาน", value=date.today())
        with r3:
            laboratory_name = st.text_input("ห้องปฏิบัติการ", value="")

        r4, r5, r6 = st.columns(3)
        with r4:
            bod = st.number_input("BOD (mg/L)", min_value=0.0, value=0.0)
            cod = st.number_input("COD (mg/L)", min_value=0.0, value=0.0)
            ss = st.number_input("SS (mg/L)", min_value=0.0, value=0.0)
        with r5:
            tkn = st.number_input("TKN (mg/L)", min_value=0.0, value=0.0)
            fecal = st.number_input("Fecal Coliform (MPN/100 mL)", min_value=0.0, value=0.0)
            total = st.number_input("Total Coliform (MPN/100 mL)", min_value=0.0, value=0.0)
        with r6:
            oil = st.number_input("Oil & Grease (mg/L)", min_value=0.0, value=0.0)
            sulfide = st.number_input("Sulfide (mg/L)", min_value=0.0, value=0.0)
            tds = st.number_input("TDS (mg/L)", min_value=0.0, value=0.0)

        ph_lab = st.number_input("pH (Lab)", min_value=0.0, max_value=14.0, value=7.0)
        lab_note = st.text_area("หมายเหตุผล Lab")

        save_lab_btn = st.form_submit_button("🧪 Save Laboratory Result", use_container_width=True)

    if save_lab_btn:
        if not DB_CONNECTED:
            st.error("ยังไม่สามารถบันทึกได้ เพราะ Cloud Database ยังไม่เชื่อมต่อ")
            st.stop()
        save_lab({
            "sample_date": sample_date.isoformat(),
            "report_date": report_date.isoformat(),
            "laboratory_name": laboratory_name,
            "bod": bod,
            "cod": cod,
            "ss": ss,
            "tkn": tkn,
            "fecal_coliform": fecal,
            "total_coliform": total,
            "oil_grease": oil,
            "sulfide": sulfide,
            "tds": tds,
            "ph_lab": ph_lab,
            "note": lab_note,
            "created_at": datetime.now().isoformat(timespec="seconds")
        })
        st.success("บันทึกผล Laboratory สำเร็จ")

    st.divider()
    if not labs.empty:
        st.dataframe(labs, use_container_width=True, hide_index=True)
    else:
        st.info("ยังไม่มีข้อมูล Laboratory")

# =========================================================
# PROCESS ANALYSIS
# =========================================================
elif page == "📊 Process Analysis":
    st.subheader("📊 Process Analysis")
    if latest_op:
        overall, alerts = classify_process(
            latest_op.get("ph_aer"),
            latest_op.get("do_aer"),
            latest_op.get("mlss"),
            latest_op.get("svi"),
            latest_op.get("fm_ratio"),
            latest_op.get("hydraulic_load"),
            latest_op.get("hrt")
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Overall", overall)
        c2.metric("SVI", "-" if latest_op.get("svi") is None else f"{latest_op.get('svi'):.1f}")
        c3.metric("F/M", "-" if latest_op.get("fm_ratio") is None else f"{latest_op.get('fm_ratio'):.3f}")
        c4.metric("HRT", "-" if latest_op.get("hrt") is None else f"{latest_op.get('hrt'):.1f} hr")

        st.write("")
        if alerts:
            for item in alerts:
                alert_box(item["level"], item["title"], item["detail"])
        else:
            alert_box("NORMAL", "Process condition", "ไม่พบเงื่อนไขแจ้งเตือนจากข้อมูลล่าสุด")
    else:
        st.info("ยังไม่มี Daily Operation สำหรับวิเคราะห์")

# =========================================================
# HISTORY
# =========================================================
elif page == "📈 Historical Data":
    st.subheader("📈 Historical Data")

    tab1, tab2 = st.tabs(["Daily Operation", "Laboratory"])
    with tab1:
        if not ops.empty:
            st.dataframe(ops, use_container_width=True, hide_index=True)
        else:
            st.info("ยังไม่มีข้อมูล Daily Operation")
    with tab2:
        if not labs.empty:
            st.dataframe(labs, use_container_width=True, hide_index=True)
        else:
            st.info("ยังไม่มีข้อมูล Laboratory")

# =========================================================
# STANDARDS
# =========================================================
elif page == "🛡️ Standards & Compliance":
    st.subheader("🛡️ Standards & Compliance")
    st.warning(
        "หน้านี้ควรตั้งค่าตามมาตรฐาน/กฎหมายที่ใช้จริงของโรงพยาบาล "
        "และควรแยก 'Operational Control Range' ออกจาก 'Legal Effluent Standard'"
    )

    st.markdown("### Operational Control Range")
    op_ref = pd.DataFrame({
        "Parameter": ["DO", "MLSS", "SVI", "pH Biological"],
        "Reference Range": ["1.5–3.0 mg/L", "2,000–4,500 mg/L", "80–150 mL/g", "6.5–8.5"],
        "Purpose": ["Aeration control", "Biomass control", "Settling condition", "Biological process"]
    })
    st.dataframe(op_ref, use_container_width=True, hide_index=True)

    st.markdown("### Legal / Permit Standard")
    st.info("เพิ่มเกณฑ์ที่ผ่านการตรวจสอบแล้วในเวอร์ชันถัดไป เพื่อให้ระบบ Compliance ใช้งานได้อย่างเป็นทางการ")

# =========================================================
# REPORTS
# =========================================================
elif page == "📄 Reports":
    st.subheader("📄 Reports")
    st.info("พื้นที่สำหรับ Daily Summary, Monthly Trend และ Quarterly Laboratory Report ในเวอร์ชันถัดไป")

# =========================================================
# SETTINGS
# =========================================================
elif page == "⚙️ Settings":
    st.subheader("⚙️ Settings")
    st.write("Database:", DB_LABEL)
    st.write("Cloud status:", "Connected" if DB_CONNECTED else "Connection error")
    st.write("Design Flow:", design_flow, "m³/day")
    st.write("Aeration Volume:", aeration_volume, "m³")
    st.caption("สามารถต่อยอดเป็น User Management, threshold settings และโรงพยาบาลหลายแห่งได้ภายหลัง")

st.markdown(
    "<div class='small-note' style='margin-top:30px;'>"
    "WIS INTELLI-WAVE PRO v7.1.1 · Cloud PostgreSQL Edition"
    "</div>",
    unsafe_allow_html=True
)
