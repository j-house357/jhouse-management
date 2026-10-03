import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta, date
import requests
import io
import os
import urllib.request

# ReportLab Imports
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- 1. การตั้งค่าหน้าเว็บ Streamlit ---
st.set_page_config(
    page_title="J-House Has Love Management System",
    page_icon="🏨",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB_FILE = "jhouse_has_love.db"

# --- 2. ฟังก์ชันจัดการฐานข้อมูล SQL (Safe Connection & Migration) ---
def get_db_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        c = conn.cursor()
        # ตารางห้องพัก
        c.execute('''CREATE TABLE IF NOT EXISTS rooms (
                        room_id TEXT PRIMARY KEY,
                        room_type TEXT,
                        base_price REAL,
                        status TEXT)''')
        
        # ตารางการจอง
        c.execute('''CREATE TABLE IF NOT EXISTS bookings (
                        booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        customer_name TEXT,
                        room_id TEXT,
                        check_in TEXT,
                        check_out TEXT,
                        total_price REAL,
                        booking_date TEXT,
                        status TEXT DEFAULT 'Confirmed',
                        booking_link TEXT DEFAULT '',
                        FOREIGN KEY(room_id) REFERENCES rooms(room_id))''')
        
        # ตารางการตั้งค่าระบบ
        c.execute('''CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT)''')
        
        # Auto-Migration: ตรวจสอบและเพิ่มคอลัมน์ booking_link กรณีใช้ฐานข้อมูลเดิม
        c.execute("PRAGMA table_info(bookings)")
        columns = [col['name'] for col in c.fetchall()]
        if 'booking_link' not in columns:
            c.execute("ALTER TABLE bookings ADD COLUMN booking_link TEXT DEFAULT ''")

        # ใส่ข้อมูลห้องพักเริ่มต้น หากยังไม่มีข้อมูล
        c.execute("SELECT COUNT(*) FROM rooms")
        if c.fetchone()[0] == 0:
            rooms_data = [
                ('101', 'Standard Room', 800.0, 'พร้อมใช้งาน'),
                ('102', 'Deluxe Room', 1200.0, 'พร้อมใช้งาน'),
                ('103', 'Suite Room', 1800.0, 'พร้อมใช้งาน')
            ]
            c.executemany("INSERT INTO rooms VALUES (?, ?, ?, ?)", rooms_data)
            
        c.execute("INSERT OR IGNORE INTO settings VALUES ('line_token', '')")
        conn.commit()

def get_setting(key, default=""):
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT value FROM settings WHERE key = ?", (key,))
            res = c.fetchone()
            return res['value'] if res else default
    except Exception:
        return default

def set_setting(key, value):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

# --- 3. ฟังก์ชันตรวจสอบห้องว่าง (ป้องกันการจองซ้ำ) ---
def is_room_available(room_id, check_in_str, check_out_str, exclude_booking_id=None):
    with get_db_connection() as conn:
        c = conn.cursor()
        query = """
            SELECT COUNT(*) FROM bookings 
            WHERE room_id = ? 
            AND status != 'Cancelled'
            AND (check_in < ? AND check_out > ?)
        """
        params = [room_id, check_out_str, check_in_str]
        if exclude_booking_id:
            query += " AND booking_id != ?"
            params.append(exclude_booking_id)
        c.execute(query, params)
        count = c.fetchone()[0]
        return count == 0

# --- 4. ฟังก์ชันคำนวณราคาตามฤดูกาล (Seasonal Pricing Breakdown) ---
def calculate_price_breakdown(room_id, check_in_dt, check_out_dt):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT base_price FROM rooms WHERE room_id = ?", (room_id,))
        res = c.fetchone()
        base_price = res['base_price'] if res else 0.0
    
    total_price = 0.0
    current_date = check_in_dt
    breakdown = []
    
    while current_date < check_out_dt:
        month = current_date.month
        if month in [11, 12, 1]:
            season_label = "High Season (+30%)"
            multiplier = 1.3
        elif month == 4:
            season_label = "Peak Season (+50%)"
            multiplier = 1.5
        else:
            season_label = "Low Season (ปกติ)"
            multiplier = 1.0
            
        day_price = base_price * multiplier
        total_price += day_price
        breakdown.append({
            'date': current_date.strftime("%Y-%m-%d"),
            'season': season_label,
            'price': day_price
        })
        current_date += timedelta(days=1)
        
    return total_price, breakdown, base_price

# --- 5. ฟังก์ชันการแจ้งเตือน LINE Notify ---
def send_line_notify(message):
    token = get_setting('line_token', '')
    if not token or token.strip() == "":
        return False
    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": f"Bearer {token}"}
    data = {"message": message}
    try:
        response = requests.post(url, headers=headers, data=data, timeout=5)
        return response.status_code == 200
    except Exception:
        return False

# --- 6. ฟังก์ชันจัดการฟอนต์ภาษาไทยและสร้าง PDF ใบเสร็จ ---
def setup_thai_pdf_font():
    font_name = "Helvetica"
    font_filename = "Sarabun-Regular.ttf"
    
    if "ThaiFont" in pdfmetrics.getRegisteredFontNames():
        return "ThaiFont"

    font_candidates = [
        font_filename,
        "THSarabunNew.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\tahoma.ttf",
        "C:\\Windows\\Fonts\\thsarabun.ttf"
    ]
    
    for fpath in font_candidates:
        if os.path.exists(fpath):
            try:
                pdfmetrics.registerFont(TTFont("ThaiFont", fpath))
                return "ThaiFont"
            except Exception:
                pass

    try:
        url = "https://github.com/google/fonts/raw/main/ofl/sarabun/Sarabun-Regular.ttf"
        urllib.request.urlretrieve(url, font_filename)
        pdfmetrics.registerFont(TTFont("ThaiFont", font_filename))
        return "ThaiFont"
    except Exception:
        return font_name

def generate_pdf_receipt(booking_info):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    
    font_name = setup_thai_pdf_font()
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontName=font_name, fontSize=16, alignment=1, spaceAfter=15)
    normal_style = ParagraphStyle('NormalStyle', parent=styles['Normal'], fontName=font_name, fontSize=11, leading=14)
    bold_style = ParagraphStyle('BoldStyle', parent=styles['Normal'], fontName=font_name, fontSize=11, leading=14)

    story.append(Paragraph("<b>ใบเสร็จรับเงิน / Receipt</b>", title_style))
    story.append(Paragraph("<b>โรงแรม เจเฮ้าส์ แฮส เลิฟ (J-House Has Love)</b>", normal_style))
    story.append(Paragraph(f"วันที่ออกเอกสาร: {datetime.now().strftime('%d/%m/%Y %H:%M น.')}", normal_style))
    story.append(Spacer(1, 15))
    
    data = [
        ["รหัสการจอง (Booking ID):", str(booking_info['id'])],
        ["ชื่อผู้เข้าพัก (Customer Name):", str(booking_info['name'])],
        ["ห้องพัก (Room):", f"ห้อง {booking_info['room_id']} ({booking_info['room_type']})"],
        ["วันที่เช็กอิน (Check-in):", str(booking_info['check_in'])],
        ["วันที่เช็กเอาต์ (Check-out):", str(booking_info['check_out'])],
        ["สถานะการจอง (Status):", "ยืนยันแล้ว (Confirmed)" if booking_info.get('status') == 'Confirmed' else "ยกเลิกแล้ว (Cancelled)"],
        ["ราคารวมสุทธิ (Total Price):", f"{booking_info['total_price']:,.2f} บาท"]
    ]
    
    if booking_info.get('booking_link'):
        data.append(["ลิงก์อ้างอิงการจอง (Booking Ref):", str(booking_info['booking_link'])])
    
    table_data = []
    for row in data:
        table_data.append([
            Paragraph(f"<b>{row[0]}</b>", bold_style),
            Paragraph(row[1], normal_style)
        ])
    
    table = Table(table_data, colWidths=[200, 300])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.whitesmoke),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.black),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BACKGROUND', (0,-1), (1,-1), colors.lightgoldenrodyellow), 
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey)
    ]))
    
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer

# --- 7. เริ่มการทำงานระบบ DB ---
init_db()

# --- 8. เมนูหลัก Sidebar ---
st.sidebar.title("🏨 J-House Has Love")
st.sidebar.caption("ระบบบริหารจัดการโรงแรมอัจฉริยะ")

menu = st.sidebar.radio(
    "เลือกเมนูการใช้งาน", 
    ["📊 ภาพรวม & ทำรายการจอง", "🗓 ปฏิทินสถานะห้องพัก", "🤖 AI วิเคราะห์ดีมานด์", "⚙ ตั้งค่าระบบ"]
)

# ==========================================
# MENU 1: ภาพรวม & ทำรายการจอง
# ==========================================
if menu == "📊 ภาพรวม & ทำรายการจอง":
    st.title("📊 ภาพรวมและระบบจองห้องพัก - J-House Has Love")
    
    with get_db_connection() as conn:
        df_rooms = pd.read_sql_query("SELECT * FROM rooms", conn)
        df_bookings = pd.read_sql_query("SELECT * FROM bookings", conn)
    
    active_bookings = df_bookings[df_bookings['status'] != 'Cancelled'] if not df_bookings.empty else pd.DataFrame()
    total_rev = active_bookings['total_price'].sum() if not active_bookings.empty else 0.0
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("ห้องพักทั้งหมด", f"{len(df_rooms)} ห้อง")
    col2.metric("รายการจองที่สมบูรณ์", f"{len(active_bookings)} รายการ")
    col3.metric("รายได้รวมทั้งหมด", f"฿{total_rev:,.2f}")
    
    available_rooms_cnt = len(df_rooms[df_rooms['status'] == 'พร้อมใช้งาน']) if not df_rooms.empty else 0
    col4.metric("ห้องพร้อมใช้งานวันนี้", f"{available_rooms_cnt} ห้อง")
    
    st.markdown("---")
    
    st.subheader("📅 ทำรายการจองห้องพักใหม่")
    
    # อ่าน URL Parameter กรณีมี Direct Link เช่น ?room=101
    query_params = st.query_params
    preset_room = query_params.get("room", None)
    if preset_room:
        st.info(f"🔗 เข้าสู่ระบบผ่านลิงก์ตรงสำหรับ: **ห้องพัก {preset_room}**")

    col_f1, col_f2 = st.columns([1, 1])
    
    with col_f1:
        customer_name = st.text_input("ชื่อ-นามสกุล ของผู้เข้าพัก", placeholder="เช่น คุณสมชาย ใจดี")
        
        active_rooms = df_rooms[df_rooms['status'] == 'พร้อมใช้งาน'] if not df_rooms.empty else pd.DataFrame()
        if active_rooms.empty:
            st.warning("ขณะนี้ไม่มีห้องพักที่พร้อมใช้งาน")
            room_options = {}
            default_index = 0
        else:
            room_options = {f"ห้อง {row['room_id']} ({row['room_type']}) - ฿{row['base_price']:,.0f}/คืน": row['room_id'] for _, row in active_rooms.iterrows()}
            
            default_index = 0
            if preset_room:
                for idx, r_id in enumerate(room_options.values()):
                    if str(r_id) == str(preset_room):
                        default_index = idx
                        break
        
        selected_room_label = st.selectbox(
            "เลือกห้องพัก", 
            list(room_options.keys()) if room_options else ["ไม่มีห้องพัก"],
            index=default_index
        )
        
        col_date1, col_date2 = st.columns(2)
        today = date.today()
        check_in = col_date1.date_input("วันเช็กอิน (Check-in)", min_value=today, value=today)
        check_out = col_date2.date_input("วันเช็กเอาต์ (Check-out)", min_value=today + timedelta(days=1), value=today + timedelta(days=1))

        booking_link_input = st.text_input("🔗 ลิงก์อ้างอิงการจอง / URL จาก Booking.com (ถ้ามี)", placeholder="https://www.booking.com/...")

    with col_f2:
        st.write("### 💰 คำนวณราคาประเมิน")
        if room_options and selected_room_label in room_options:
            room_id = room_options[selected_room_label]
            if check_out > check_in:
                total_price, breakdown, base_price = calculate_price_breakdown(room_id, check_in, check_out)
                nights = (check_out - check_in).days
                
                st.info(f"ระยะเวลาเข้าพัก: **{nights} คืน** | ราคาฐาน: **฿{base_price:,.2f}/คืน**")
                st.metric("ราคารวมสุทธิ (คำนวณตามอัตราฤดูกาล)", f"฿{total_price:,.2f}")
                
                with st.expander("🔍 ดูรายละเอียดราคารายวัน"):
                    df_breakdown = pd.DataFrame(breakdown)
                    df_breakdown.columns = ['วันที่', 'ช่วงฤดูกาล', 'ราคา (บาท)']
                    st.dataframe(df_breakdown, use_container_width=True)
            else:
                st.error("วันเช็กเอาต์ต้องอยู่หลังวันเช็กอินอย่างน้อย 1 วัน")
    
    if st.button("🚀 ยืนยันการทำรายการจอง", type="primary", use_container_width=True):
        if not customer_name.strip():
            st.error("กรุณากรอกชื่อ-นามสกุล ของผู้เข้าพัก")
        elif check_in >= check_out:
            st.error("วันเช็กเอาต์ต้องอยู่หลังวันเช็กอินอย่างน้อย 1 วัน")
        elif not room_options:
            st.error("ไม่มีห้องพักที่สามารถจองได้")
        else:
            room_id = room_options[selected_room_label]
            check_in_str = str(check_in)
            check_out_str = str(check_out)
            
            if not is_room_available(room_id, check_in_str, check_out_str):
                st.error(f"❌ ห้องพักหมายเลข {room_id} ถูกจองแล้วในช่วงวันที่ {check_in_str} ถึง {check_out_str} กรุณาเลือกช่วงเวลาหรือห้องพักอื่น")
            else:
                total_price, _, _ = calculate_price_breakdown(room_id, check_in, check_out)
                
                with get_db_connection() as conn:
                    c = conn.cursor()
                    c.execute("""
                        INSERT INTO bookings (customer_name, room_id, check_in, check_out, total_price, booking_date, status, booking_link) 
                        VALUES (?, ?, ?, ?, ?, ?, 'Confirmed', ?)
                    """, (customer_name.strip(), room_id, check_in_str, check_out_str, total_price, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), booking_link_input.strip()))
                    booking_id = c.lastrowid
                    conn.commit()
                
                st.balloons()
                st.success(f"🎉 ทำรายการจองสำเร็จ! รหัสการจองคือ #{booking_id} ยอดรวมทั้งสิ้น: {total_price:,.2f} บาท")
                
                line_msg = f"\n🔔 มีรายการจองใหม่!\nระบบ: J-House Has Love\nรหัสการจอง: #{booking_id}\nผู้เข้าพัก: {customer_name}\nห้องพัก: {room_id}\nเช็กอิน: {check_in_str}\nเช็กเอาต์: {check_out_str}\nยอดรวม: {total_price:,.2f} บาท"
                if booking_link_input.strip():
                    line_msg += f"\nลิงก์อ้างอิง: {booking_link_input.strip()}"

                if send_line_notify(line_msg):
                    st.toast("ส่งข้อความแจ้งเตือนผ่าน LINE เรียบร้อยแล้ว", icon="📲")
                st.rerun()

    st.markdown("---")
    st.subheader("📋 ประวัติการจองห้องพักและพิมพ์ใบเสร็จ")
    
    with get_db_connection() as conn:
        query = """
        SELECT b.booking_id, b.customer_name, b.room_id, r.room_type, b.check_in, b.check_out, b.total_price, b.status, b.booking_link 
        FROM bookings b 
        LEFT JOIN rooms r ON b.room_id = r.room_id
        ORDER BY b.booking_id DESC
        """
        df_all_bookings = pd.read_sql_query(query, conn)
    
    if not df_all_bookings.empty:
        df_all_bookings['room_type'] = df_all_bookings['room_type'].fillna('ทั่วไป')
    
    col_s1, col_s2 = st.columns([2, 1])
    search_term = col_s1.text_input("🔍 ค้นหาด้วยชื่อผู้เข้าพัก หรือรหัสการจอง", "")
    filter_status = col_s2.selectbox("กรองตามสถานะ", ["ทั้งหมด", "Confirmed", "Cancelled"])
    
    filtered_df = df_all_bookings.copy()
    if search_term and not filtered_df.empty:
        filtered_df = filtered_df[
            filtered_df['customer_name'].str.contains(search_term, case=False, na=False) |
            filtered_df['booking_id'].astype(str).str.contains(search_term, na=False)
        ]
    if filter_status != "ทั้งหมด" and not filtered_df.empty:
        filtered_df = filtered_df[filtered_df['status'] == filter_status]
        
    if not filtered_df.empty:
        for _, row in filtered_df.iterrows():
            status_label = "🟢 ยืนยันแล้ว" if row['status'] == 'Confirmed' else "🔴 ยกเลิกแล้ว"
            with st.expander(f"{status_label} | การจอง #{row['booking_id']} - คุณ {row['customer_name']} (ห้อง {row['room_id']})"):
                c1, c2, c3 = st.columns([2, 2, 1])
                with c1:
                    st.write(f"**ประเภทห้องพัก:** {row['room_type']}")
                    st.write(f"**วันเช็กอิน:** {row['check_in']}")
                    st.write(f"**วันเช็กเอาต์:** {row['check_out']}")
                with c2:
                    st.write(f"**ราคารวมสุทธิ:** ฿{row['total_price']:,.2f}")
                    st.write(f"**สถานะ:** {row['status']}")
                    if row.get('booking_link') and str(row['booking_link']).startswith("http"):
                        st.link_button("🔗 เปิดลิงก์ Booking.com / Ref", url=row['booking_link'])
                    elif row.get('booking_link'):
                        st.write(f"**หมายเลขอ้างอิง:** {row['booking_link']}")

                with c3:
                    booking_info = {
                        'id': row['booking_id'],
                        'name': row['customer_name'],
                        'room_id': row['room_id'],
                        'room_type': row['room_type'],
                        'check_in': row['check_in'],
                        'check_out': row['check_out'],
                        'total_price': row['total_price'],
                        'status': row['status'],
                        'booking_link': row.get('booking_link', '')
                    }
                    pdf_data = generate_pdf_receipt(booking_info)
                    st.download_button(
                        label="📄 พิมพ์ใบเสร็จ PDF",
                        data=pdf_data,
                        file_name=f"Receipt_JHouseHasLove_{row['booking_id']}.pdf",
                        mime="application/pdf",
                        key=f"pdf_{row['booking_id']}"
                    )
                    
                    if row['status'] == 'Confirmed':
                        if st.button("❌ ยกเลิกการจอง", key=f"cancel_{row['booking_id']}"):
                            with get_db_connection() as conn:
                                c = conn.cursor()
                                c.execute("UPDATE bookings SET status = 'Cancelled' WHERE booking_id = ?", (row['booking_id'],))
                                conn.commit()
                            st.warning(f"ยกเลิกการจองรายการ #{row['booking_id']} เรียบร้อยแล้ว")
                            st.rerun()
    else:
        st.info("ไม่พบข้อมูลการจองในระบบ")

# ==========================================
# MENU 2: ปฏิทินสถานะห้องพัก
# ==========================================
elif menu == "🗓 ปฏิทินสถานะห้องพัก":
    st.title("🗓 ปฏิทินสถานะการเข้าพักรายวัน (Occupancy Grid)")
    
    with get_db_connection() as conn:
        df_rooms = pd.read_sql_query("SELECT room_id, room_type FROM rooms ORDER BY room_id", conn)
        df_bookings = pd.read_sql_query("SELECT * FROM bookings WHERE status != 'Cancelled'", conn)
    
    col_d1, col_d2 = st.columns(2)
    start_view_date = col_d1.date_input("แสดงปฏิทินตั้งแต่วันที่", date.today())
    days_to_show = col_d2.slider("จำนวนวันที่ต้องการแสดง (วัน)", min_value=7, max_value=30, value=14)
    
    st.markdown("### 📅 ตารางสถานะห้องพักรายวัน")
    
    date_list = [start_view_date + timedelta(days=i) for i in range(days_to_show)]
    matrix_data = []
    
    for _, room in df_rooms.iterrows():
        row_dict = {'ห้องพัก': f"ห้อง {room['room_id']} ({room['room_type']})"}
        for d in date_list:
            d_str = d.strftime("%Y-%m-%d")
            occupied = False
            guest_name = ""
            if not df_bookings.empty:
                for _, b in df_bookings.iterrows():
                    if b['room_id'] == room['room_id'] and b['check_in'] <= d_str < b['check_out']:
                        occupied = True
                        guest_name = b['customer_name']
                        break
            col_key = d.strftime("%d/%m")
            row_dict[col_key] = f"🔴 {guest_name}" if occupied else "🟢 ว่าง"
        matrix_data.append(row_dict)
        
    df_matrix = pd.DataFrame(matrix_data)
    st.dataframe(df_matrix, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    st.subheader("📋 รายละเอียดรายการจองทั้งหมด")
    if not df_bookings.empty:
        df_bookings_display = df_bookings[['booking_id', 'customer_name', 'room_id', 'check_in', 'check_out', 'total_price', 'status', 'booking_link']]
        st.dataframe(df_bookings_display, use_container_width=True)
    else:
        st.info("ยังไม่มีข้อมูลการจองในระบบ")

# ==========================================
# MENU 3: AI วิเคราะห์ดีมานด์
# ==========================================
elif menu == "🤖 AI วิเคราะห์ดีมานด์":
    st.title("🤖 AI วิเคราะห์ความต้องการและแนวโน้มรายได้")
    st.caption("ระบบประเมินอัตราการเข้าพัก (Occupancy Rate) และวิเคราะห์การกำหนดราคาแบบยืดหยุ่น (Dynamic Pricing)")
    
    with get_db_connection() as conn:
        df_b = pd.read_sql_query("SELECT * FROM bookings WHERE status != 'Cancelled'", conn)
        df_r = pd.read_sql_query("SELECT * FROM rooms", conn)
    
    if df_b.empty:
        st.info("💡 ยังมีข้อมูลการจองไม่เพียงพอสำหรับการวิเคราะห์เชิงลึก กรุณาเพิ่มข้อมูลการจองในระบบ")
    else:
        total_revenue = df_b['total_price'].sum()
        total_bookings = len(df_b)
        total_rooms_cnt = len(df_r) if len(df_r) > 0 else 1
        
        df_b['check_in_dt'] = pd.to_datetime(df_b['check_in'])
        df_b['check_out_dt'] = pd.to_datetime(df_b['check_out'])
        df_b['nights'] = (df_b['check_out_dt'] - df_b['check_in_dt']).dt.days
        total_nights_booked = df_b['nights'].sum()
        
        adr = total_revenue / total_nights_booked if total_nights_booked > 0 else 0
        revpar = total_revenue / (total_rooms_cnt * 30)
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("ยอดขายรวมสุทธิ", f"฿{total_revenue:,.2f}")
        c2.metric("จำนวนคืนที่ถูกจอง", f"{total_nights_booked} คืน")
        c3.metric("ADR (ราคาห้องพักเฉลี่ยต่อวัน)", f"฿{adr:,.2f}")
        c4.metric("RevPAR (รายได้เฉลี่ยต่อห้องพักทั้งหมด)", f"฿{revpar:,.2f}")
        
        st.markdown("---")
        
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            st.subheader("📊 สัดส่วนรายได้ตามประเภทห้องพัก")
            df_merged = df_b.merge(df_r, on='room_id', how='left')
            df_merged['room_type'] = df_merged['room_type'].fillna('ทั่วไป')
            rev_by_type = df_merged.groupby('room_type')['total_price'].sum().reset_index()
            rev_by_type.columns = ['ประเภทห้องพัก', 'รายได้รวม (บาท)']
            st.bar_chart(rev_by_type.set_index('ประเภทห้องพัก'))
            
        with col_chart2:
            st.subheader("📈 แนวโน้มรายได้ตามวันที่เช็กอิน")
            daily_rev = df_b.groupby('check_in_dt')['total_price'].sum().reset_index()
            st.line_chart(daily_rev.set_index('check_in_dt'))
            
        st.markdown("---")
        st.subheader("💡 คำแนะนำการกำหนดราคาจากระบบ AI (Smart Pricing Insights)")
        
        if total_nights_booked > 20:
            st.success("🔥 **ความต้องการห้องพักสูง (High Demand):** ช่วงนี้มีอัตราการจองสูง แนะนำให้ปรับเพิ่มราคาฐานขึ้น 10-15% สำหรับห้องพักทุกประเภทเพื่อเพิ่มผลกำไรสูงสุด")
        else:
            st.info("📉 **กลยุทธ์ช่วงความต้องการปกติ/ต่ำ (Low Demand):** ช่วงนี้การจองค่อนข้างทรงตัว แนะนำให้จัดโปรโมชั่นพิเศษ เช่น แถมอาหารเช้า หรือส่วนลดวันธรรมดา (จันทร์-พฤหัสบดี) เพื่อกระตุ้นยอดเข้าพัก")

# ==========================================
# MENU 4: ตั้งค่าระบบ & จัดการห้องพัก
# ==========================================
elif menu == "⚙ ตั้งค่าระบบ":
    st.title("⚙ ตั้งค่าระบบและจัดการห้องพัก")
    
    tab1, tab2, tab3 = st.tabs(["🏨 จัดการข้อมูลห้องพัก", "📲 ตั้งค่าการแจ้งเตือน LINE Notify", "💾 การส่งออกข้อมูล"])
    
    # TAB 1: จัดการห้องพัก
    with tab1:
        st.subheader("➕ เพิ่มรายการห้องพักใหม่")
        with st.form("add_room_form", clear_on_submit=True):
            col_r1, col_r2, col_r3 = st.columns(3)
            new_room_id = col_r1.text_input("หมายเลขห้องพัก (Room ID)", placeholder="เช่น 104")
            new_room_type = col_r2.selectbox("ประเภทห้องพัก", ["Standard Room", "Deluxe Room", "Suite Room", "VIP Family Room"])
            new_base_price = col_r3.number_input("ราคาฐานเริ่มต้น (บาท/คืน)", min_value=100.0, value=1000.0, step=100.0)
            
            submit_room = st.form_submit_button("บันทึกข้อมูลห้องพัก")
            if submit_room:
                if not new_room_id.strip():
                    st.error("กรุณาระบุหมายเลขห้องพัก")
                else:
                    try:
                        with get_db_connection() as conn:
                            c = conn.cursor()
                            c.execute("INSERT INTO rooms VALUES (?, ?, ?, 'พร้อมใช้งาน')", (new_room_id.strip(), new_room_type, new_base_price))
                            conn.commit()
                        st.success(f"เพิ่มห้องพักหมายเลข {new_room_id} เรียบร้อยแล้ว")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error(f"❌ หมายเลขห้องพัก {new_room_id} มีอยู่ในระบบแล้ว กรุณาใช้หมายเลขอื่น")

        st.markdown("---")
        st.subheader("📋 รายการห้องพักทั้งหมด")
        with get_db_connection() as conn:
            df_rooms_edit = pd.read_sql_query("SELECT * FROM rooms", conn)
        
        if not df_rooms_edit.empty:
            for idx, r_row in df_rooms_edit.iterrows():
                c_r1, c_r2, c_r3, c_r4, c_r5 = st.columns([1, 2, 2, 2, 1])
                c_r1.write(f"**ห้อง {r_row['room_id']}**")
                c_r2.write(r_row['room_type'])
                c_r3.write(f"฿{r_row['base_price']:,.2f}")
                
                new_status = c_r4.selectbox("สถานะ", ["พร้อมใช้งาน", "ปิดปรับปรุง"], index=0 if r_row['status'] == 'พร้อมใช้งาน' else 1, key=f"status_{r_row['room_id']}")
                if new_status != r_row['status']:
                    with get_db_connection() as conn:
                        c = conn.cursor()
                        c.execute("UPDATE rooms SET status = ? WHERE room_id = ?", (new_status, r_row['room_id']))
                        conn.commit()
                    st.toast(f"อัปเดตสถานะห้องพัก {r_row['room_id']} เป็น {new_status}")
                    st.rerun()
                    
                if c_r5.button("🗑 ลบ", key=f"del_room_{r_row['room_id']}"):
                    with get_db_connection() as conn:
                        c = conn.cursor()
                        c.execute("SELECT COUNT(*) FROM bookings WHERE room_id = ? AND status = 'Confirmed'", (r_row['room_id'],))
                        active_b_count = c.fetchone()[0]
                        
                        if active_b_count > 0:
                            st.error(f"ไม่สามารถลบห้องพัก {r_row['room_id']} ได้ เนื่องจากมีรายการจองที่ยังรอดำเนินการอยู่ {active_b_count} รายการ")
                        else:
                            c.execute("DELETE FROM rooms WHERE room_id = ?", (r_row['room_id'],))
                            conn.commit()
                            st.warning(f"ลบห้องพักหมายเลข {r_row['room_id']} เรียบร้อยแล้ว")
                            st.rerun()
        else:
            st.info("ยังไม่มีข้อมูลห้องพักในระบบ")

    # TAB 2: ตั้งค่า LINE Notify
    with tab2:
        st.subheader("📲 ตั้งค่า LINE Notify Access Token")
        current_token = get_setting('line_token', '')
        
        token_input = st.text_input("LINE Notify Access Token", value=current_token, type="password", help="สามารถขอรับ Token ได้จาก https://notify-bot.line.me/")
        
        col_t1, col_t2 = st.columns(2)
        if col_t1.button("💾 บันทึก Token", type="primary"):
            set_setting('line_token', token_input.strip())
            st.success("บันทึก LINE Notify Token เรียบร้อยแล้ว")
            
        if col_t2.button("🔔 ส่งข้อความทดสอบ"):
            if send_line_notify("\n🔔 ทดสอบการเชื่อมต่อระบบ J-House Has Love Management System"):
                st.success("ส่งข้อความทดสอบสำเร็จ! กรุณาตรวจสอบในแอปพลิเคชัน LINE")
            else:
                st.error("ไม่สามารถส่งข้อความได้ กรุณาตรวจสอบ Access Token อีกครั้ง")

    # TAB 3: การส่งออกข้อมูล
    with tab3:
        st.subheader("💾 ส่งออกข้อมูลระบบ")
        with get_db_connection() as conn:
            df_exp_b = pd.read_sql_query("SELECT * FROM bookings", conn)
        
        if not df_exp_b.empty:
            csv_b = df_exp_b.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 ดาวน์โหลดข้อมูลการจองเป็นไฟล์ CSV",
                data=csv_b,
                file_name=f"jhouse_has_love_bookings_{date.today()}.csv",
                mime="text/csv"
            )
        else:
            st.info("ยังไม่มีข้อมูลการจองสำหรับส่งออก")
