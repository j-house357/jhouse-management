import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta
import requests
import os
import io
import urllib.request

# ReportLab Imports
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- 1. ตั้งค่าหน้าเว็บ Streamlit ---
st.set_page_config(
    page_title="J-House Has Love Management System",
    page_icon="🏨",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB_FILE = "jhouse_has_love.db"

# --- 2. การจัดการฐานข้อมูล (Database) ---
def get_db_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # ตารางห้องพัก
    c.execute('''
        CREATE TABLE IF NOT EXISTS rooms (
            room_id TEXT PRIMARY KEY,
            room_type TEXT NOT NULL,
            base_price REAL NOT NULL,
            base_capacity INTEGER DEFAULT 2,
            extra_person_fee REAL DEFAULT 200.0,
            status TEXT DEFAULT 'ว่าง'
        )
    ''')
    # ตารางการจอง
    c.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guest_name TEXT NOT NULL,
            guest_phone TEXT,
            room_id TEXT NOT NULL,
            check_in DATE NOT NULL,
            check_out DATE NOT NULL,
            num_guests INTEGER DEFAULT 1,
            total_price REAL NOT NULL,
            booking_status TEXT DEFAULT 'ยืนยันแล้ว',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (room_id) REFERENCES rooms (room_id)
        )
    ''')
    # ตารางตั้งค่า
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # Auto Migration
    c.execute("PRAGMA table_info(rooms)")
    cols = [col[1] for col in c.fetchall()]
    if 'base_capacity' not in cols:
        c.execute("ALTER TABLE rooms ADD COLUMN base_capacity INTEGER DEFAULT 2")
    if 'extra_person_fee' not in cols:
        c.execute("ALTER TABLE rooms ADD COLUMN extra_person_fee REAL DEFAULT 200.0")
        
    conn.commit()
    conn.close()

init_db()

# --- 3. ฟังก์ชันช่วยเหลือ & LINE Notify ---
def get_setting(key, default=""):
    conn = get_db_connection()
    res = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return res['value'] if res else default

def set_setting(key, value):
    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def send_line_notify(message):
    token = get_setting("line_token", "")
    if not token:
        return False
    url = 'https://notify-api.line.me/api/notify'
    headers = {'content-type': 'application/x-www-form-urlencoded', 'Authorization': 'Bearer ' + token}
    r = requests.post(url, headers=headers, data={'message': message})
    return r.status_code == 200

def check_room_availability(room_id, check_in, check_out, exclude_id=None):
    conn = get_db_connection()
    query = '''
        SELECT COUNT(*) as count FROM bookings 
        WHERE room_id = ? 
        AND booking_status != 'ยกเลิก'
        AND NOT (check_out <= ? OR check_in >= ?)
    '''
    params = [room_id, check_in, check_out]
    if exclude_id:
        query += " AND booking_id != ?"
        params.append(exclude_id)
    res = conn.execute(query, params).fetchone()
    conn.close()
    return res['count'] == 0

# --- 4. ฟังก์ชันสร้างใบเสร็จ PDF ภาษาไทย ---
def generate_pdf_receipt(booking_id, guest_name, guest_phone, room_id, check_in, check_out, num_guests, total_price):
    font_path = "THSarabunNew.ttf"
    if not os.path.exists(font_path):
        try:
            url = "https://github.com/google/fonts/raw/main/ofl/thsarabunnew/THSarabunNew.ttf"
            urllib.request.urlretrieve(url, font_path)
        except:
            pass
            
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('THSarabunNew', font_path))
        font_name = 'THSarabunNew'
    else:
        font_name = 'Helvetica'

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Normal'], fontName=font_name, fontSize=22, leading=26, alignment=1, textColor=colors.HexColor("#1E3A8A"))
    normal_style = ParagraphStyle('NormalStyle', parent=styles['Normal'], fontName=font_name, fontSize=14, leading=18)
    bold_style = ParagraphStyle('BoldStyle', parent=styles['Normal'], fontName=font_name, fontSize=14, leading=18, textColor=colors.HexColor("#1E3A8A"))
    
    elements = []
    elements.append(Paragraph("<b>ใบเสร็จรับเงิน / Receipt</b>", title_style))
    elements.append(Paragraph("<b>เจเฮาส์มีความรัก (J-House Has Love)</b>", title_style))
    elements.append(Spacer(1, 15))
    
    data = [
        [Paragraph(f"<b>เลขที่ใบเสร็จ:</b> #{booking_id}", normal_style), Paragraph(f"<b>วันที่ออกใบเสร็จ:</b> {datetime.now().strftime('%d/%m/%Y')}", normal_style)],
        [Paragraph(f"<b>ชื่อผู้เข้าพัก:</b> {guest_name}", normal_style), Paragraph(f"<b>เบอร์โทรศัพท์:</b> {guest_phone}", normal_style)],
        [Paragraph(f"<b>ห้องพัก:</b> {room_id}", normal_style), Paragraph(f"<b>จำนวนผู้เข้าพัก:</b> {num_guests} ท่าน", normal_style)],
        [Paragraph(f"<b>วันเช็กอิน:</b> {check_in}", normal_style), Paragraph(f"<b>วันเช็กเอาต์:</b> {check_out}", normal_style)],
    ]
    t1 = Table(data, colWidths=[270, 270])
    t1.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('BOTTOMPADDING', (0,0), (-1,-1), 6)]))
    elements.append(t1)
    elements.append(Spacer(1, 15))
    
    table_data = [
        [Paragraph("<b>รายการ</b>", bold_style), Paragraph("<b>จำนวนเงิน (บาท)</b>", bold_style)],
        [Paragraph(f"ค่าห้องพัก {room_id} ({check_in} ถึง {check_out})", normal_style), Paragraph(f"{total_price:,.2f}", normal_style)],
        [Paragraph("<b>ยอดชำระสุทธิ</b>", bold_style), Paragraph(f"<b>{total_price:,.2f}</b>", bold_style)]
    ]
    t2 = Table(table_data, colWidths=[380, 160])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#F3F4F6")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#D1D5DB")),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    elements.append(t2)
    elements.append(Spacer(1, 30))
    elements.append(Paragraph("ขอบคุณที่ใช้บริการ เจเฮาส์มีความรัก ขอให้ท่านเดินทางโดยสวัสดิภาพ", ParagraphStyle('End', parent=normal_style, alignment=1)))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer

# --- 5. เมนูหลัก Streamlit ---
st.title("🏨 ระบบจัดการโรงแรม - เจเฮาส์มีความรัก")

menu = st.sidebar.radio(
    "📌 เมนูหลัก",
    ["📊 ทำรายการจอง", "📅 ปฏิทิน / สถานะการจอง", "⚙️ ตั้งค่าห้องพักและระบบ", "📤 ส่งออกข้อมูล"]
)

# ---------------------------------------------------------
# MENU 1: BOOKING
# ---------------------------------------------------------
if menu == "📊 ทำรายการจอง":
    st.header("📊 ทำรายการจองห้องพัก")
    conn = get_db_connection()
    rooms = conn.execute("SELECT * FROM rooms").fetchall()
    conn.close()
    
    if not rooms:
        st.warning("⚠️ ยังไม่มีรายการห้องพัก กรุณาไปเพิ่มห้องพักในเมนู '⚙️ ตั้งค่าห้องพักและระบบ' ก่อนครับ")
    else:
        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader("📝 ข้อมูลการจอง")
            guest_name = st.text_input("ชื่อ-นามสกุล ผู้เข้าพัก *")
            guest_phone = st.text_input("เบอร์โทรศัพท์")
            
            room_dict = {f"ห้อง {r['room_id']} ({r['room_type']}) - เริ่มต้น {r['base_price']:,.0f}B": r for r in rooms}
            selected_label = st.selectbox("เลือกห้องพัก", list(room_dict.keys()))
            selected_room = room_dict[selected_label]
            
            cin_col, cout_col = st.columns(2)
            check_in = cin_col.date_input("วันเช็กอิน", date.today())
            check_out = cout_col.date_input("วันเช็กเอาต์", date.today() + timedelta(days=1))
            
            num_guests = st.number_input("จำนวนผู้เข้าพัก (คน)", min_value=1, value=int(selected_room['base_capacity']))
            
        with col2:
            st.subheader("💰 คำนวณราคา")
            nights = (check_out - check_in).days
            if nights <= 0:
                st.error("วันเช็กเอาต์ต้องอยู่หลังวันเช็กอินอย่างน้อย 1 คืน")
                nights = 1
                
            b_price = selected_room['base_price']
            b_cap = selected_room['base_capacity']
            e_fee = selected_room['extra_person_fee']
            
            extra_ppl = max(0, num_guests - b_cap)
            extra_total = extra_ppl * e_fee
            nightly_rate = b_price + extra_total
            calc_total = nightly_rate * nights
            
            st.info(f"""
            * **ราคาห้องพัก**: {b_price:,.2f} บาท/คืน (รองรับ {b_cap} ท่านแรก)
            * **คนเกิน**: {extra_ppl} ท่าน (+{extra_total:,.2f} บาท/คืน)
            * **จำนวน**: {nights} คืน
            * **ราคารวมคำนวณ**: **{calc_total:,.2f} บาท**
            """)
            
            final_price = st.number_input("ราคาขายจริง/สุทธิ (บาท)", min_value=0.0, value=float(calc_total), step=100.0)
            
            if st.button("✅ ยืนยันการจอง & ออกใบเสร็จ", type="primary", use_container_width=True):
                if not guest_name:
                    st.error("กรุณากรอกชื่อผู้เข้าพัก")
                elif not check_room_availability(selected_room['room_id'], check_in, check_out):
                    st.error(f"❌ ห้อง {selected_room['room_id']} ไม่ว่างในช่วงวันที่เลือก")
                else:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute('''
                        INSERT INTO bookings (guest_name, guest_phone, room_id, check_in, check_out, num_guests, total_price)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (guest_name, guest_phone, selected_room['room_id'], check_in, check_out, num_guests, final_price))
                    bid = cur.lastrowid
                    conn.commit()
                    conn.close()
                    
                    st.success(f"🎉 บันทึกการจองสำเร็จ! (หมายเลขการจอง #{bid})")
                    
                    msg = f"\n🎉 มีรายการจองใหม่ #{bid}\nคุณ: {guest_name}\nห้อง: {selected_room['room_id']}\nเข้าพัก: {check_in} ถึง {check_out}\nจำนวน: {num_guests} ท่าน\nราคารวม: {final_price:,.2f} บาท"
                    send_line_notify(msg)
                    
                    pdf_data = generate_pdf_receipt(bid, guest_name, guest_phone, selected_room['room_id'], check_in, check_out, num_guests, final_price)
                    st.download_button(
                        label="📄 ดาวน์โหลดใบเสร็จรับเงิน (PDF)",
                        data=pdf_data,
                        file_name=f"Receipt_{bid}_{guest_name}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )

# ---------------------------------------------------------
# MENU 2: CALENDAR & BOOKINGS MANAGEMENT
# ---------------------------------------------------------
elif menu == "📅 ปฏิทิน / สถานะการจอง":
    st.header("📅 ตารางรายการจองและจัดการสถานะ")
    
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT * FROM bookings ORDER BY check_in DESC", conn)
    conn.close()
    
    if df.empty:
        st.info("ยังไม่มีข้อมูลการจองในระบบ")
    else:
        st.dataframe(df, use_container_width=True)
        
        st.subheader("🛠️ อัปเดตสถานะการจอง")
        c1, c2, c3 = st.columns([1, 2, 1])
        sel_id = c1.selectbox("เลือก ID การจอง", df['booking_id'])
        new_status = c2.radio("เปลี่ยนสถานะเป็น", ["เช็กอินแล้ว", "เช็กเอาต์แล้ว", "ยกเลิก"], horizontal=True)
        
        if c3.button("อัปเดตสถานะ"):
            conn = get_db_connection()
            conn.execute("UPDATE bookings SET booking_status=? WHERE booking_id=?", (new_status, sel_id))
            conn.commit()
            conn.close()
            st.success(f"อัปเดตการจอง #{sel_id} เป็น '{new_status}' เรียบร้อยแล้ว")
            st.rerun()

# ---------------------------------------------------------
# MENU 3: ROOM & SYSTEM SETTINGS
# ---------------------------------------------------------
elif menu == "⚙️️ ตั้งค่าห้องพักและระบบ":
    st.header("⚙️ ตั้งค่าห้องพักและระบบ")
    
    tab_room, tab_line = st.tabs(["🏠 จัดการห้องพักและราคา", "🔔 ตั้งค่า LINE Notify"])
    
    with tab_room:
        st.subheader("➕ เพิ่มห้องพักใหม่")
        with st.form("add_room"):
            a1, a2, a3 = st.columns(3)
            r_id = a1.text_input("หมายเลขห้องพัก (เช่น 101)")
            r_type = a2.selectbox("ประเภทห้อง", ["Standard Room", "Deluxe Room", "Suite", "Family Room"])
            r_price = a3.number_input("ราคาเริ่มต้น (บาท/คืน)", min_value=0.0, value=800.0, step=100.0)
            
            a4, a5 = st.columns(2)
            r_cap = a4.number_input("พักได้มาตรฐาน (คน)", min_value=1, value=2)
            r_extra = a5.number_input("ค่าบริการคนเกิน (บาท/คน/คืน)", min_value=0.0, value=200.0, step=50.0)
            
            if st.form_submit_button("บันทึกห้องพักใหม่"):
                if r_id:
                    conn = get_db_connection()
                    try:
                        conn.execute("INSERT INTO rooms (room_id, room_type, base_price, base_capacity, extra_person_fee) VALUES (?,?,?,?,?)",
                                     (r_id, r_type, r_price, r_cap, r_extra))
                        conn.commit()
                        st.success(f"เพิ่มห้อง {r_id} เรียบร้อยแล้ว")
                    except sqlite3.IntegrityError:
                        st.error(f"ห้อง {r_id} มีอยู่ในระบบแล้ว")
                    finally:
                        conn.close()
                        st.rerun()
                else:
                    st.error("กรุณาระบุเลขห้อง")

        st.divider()
        st.subheader("📋 รายการห้องพักทั้งหมด (แก้ไข/ลบ)")
        
        conn = get_db_connection()
        rooms = conn.execute("SELECT * FROM rooms").fetchall()
        conn.close()
        
        for r in rooms:
            with st.expander(f"🏠 ห้อง {r['room_id']} - {r['room_type']} (ราคาฐาน: {r['base_price']:,.0f} บาท)"):
                with st.form(f"edit_form_{r['room_id']}"):
                    e1, e2, e3 = st.columns(3)
                    utype = e1.selectbox("ประเภทห้อง", ["Standard Room", "Deluxe Room", "Suite", "Family Room"],
                                          index=["Standard Room", "Deluxe Room", "Suite", "Family Room"].index(r['room_type']) if r['room_type'] in ["Standard Room", "Deluxe Room", "Suite", "Family Room"] else 0)
                    uprice = e2.number_input("ราคาฐาน (บาท)", min_value=0.0, value=float(r['base_price']), step=100.0)
                    ustatus = e3.selectbox("สถานะ", ["ว่าง", "มีผู้เข้าพัก", "ปิดปรับปรุง"], index=["ว่าง", "มีผู้เข้าพัก", "ปิดปรับปรุง"].index(r['status']) if r['status'] in ["ว่าง", "มีผู้เข้าพัก", "ปิดปรับปรุง"] else 0)
                    
                    e4, e5 = st.columns(2)
                    ucap = e4.number_input("พักมาตรฐาน (คน)", min_value=1, value=int(r['base_capacity']))
                    uextra = e5.number_input("ค่าคนเกิน (บาท/คน)", min_value=0.0, value=float(r['extra_person_fee']), step=50.0)
                    
                    b_save, b_del = st.columns([1, 1])
                    if b_save.form_submit_button("💾 บันทึกการแก้ไข"):
                        conn = get_db_connection()
                        conn.execute("UPDATE rooms SET room_type=?, base_price=?, base_capacity=?, extra_person_fee=?, status=? WHERE room_id=?",
                                     (utype, uprice, ucap, uextra, ustatus, r['room_id']))
                        conn.commit()
                        conn.close()
                        st.success(f"อัปเดตห้อง {r['room_id']} สำเร็จ!")
                        st.rerun()
                        
                    if b_del.form_submit_button("🗑️ ลบห้องนี้", type="primary"):
                        conn = get_db_connection()
                        conn.execute("DELETE FROM rooms WHERE room_id=?", (r['room_id'],))
                        conn.commit()
                        conn.close()
                        st.warning(f"ลบห้อง {r['room_id']} แล้ว")
                        st.rerun()

    with tab_line:
        st.subheader("🔔 ตั้งค่า LINE Notify Token")
        token = get_setting("line_token", "")
        new_token = st.text_input("LINE Notify Token", value=token, type="password")
        if st.button("บันทึก Token"):
            set_setting("line_token", new_token)
            st.success("บันทึกเรียบร้อย!")
        if st.button("🧪 ทดสอบส่งข้อความ"):
            if send_line_notify("ทดสอบระบบแจ้งเตือน เจเฮาส์มีความรัก"):
                st.success("ส่งข้อความสำเร็จ!")
            else:
                st.error("ส่งข้อความไม่สำเร็จ ตรวจสอบ Token อีกครั้ง")

# ---------------------------------------------------------
# MENU 4: EXPORT DATA & MONTHLY REVENUE SUMMARY
# ---------------------------------------------------------
elif menu == "📤 ส่งออกข้อมูล":
    st.header("📤 ส่งออกข้อมูลและการสรุปยอดขาย")
    
    conn = get_db_connection()
    df_exp = pd.read_sql_query("SELECT * FROM bookings ORDER BY created_at DESC", conn)
    conn.close()
    
    if df_exp.empty:
        st.info("ยังไม่มีข้อมูลสำหรับการส่งออก")
    else:
        # --- ส่วนที่เพิ่มใหม่: สรุปยอดขายรายเดือน ---
        st.subheader("📈 สรุปยอดขายรายเดือน (Monthly Revenue Summary)")
        
        # แปลง created_at เป็น datetime และดึงคอลัมน์ ปี-เดือน (YM)
        df_summary = df_exp[df_exp['booking_status'] != 'ยกเลิก'].copy()
        if not df_summary.empty:
            df_summary['created_at'] = pd.to_datetime(df_summary['created_at'])
            df_summary['YearMonth'] = df_summary['created_at'].dt.to_period('M').astype(str)
            
            # จัดกลุ่มคำนวณยอดรวมและจำนวนการจอง
            revenue_monthly = df_summary.groupby('YearMonth').agg(
                Total_Bookings=('booking_id', 'count'),
                Total_Revenue=('total_price', 'sum')
            ).reset_index()
            
            revenue_monthly.columns = ['ปี-เดือน', 'จำนวนการจอง (รายการ)', 'ยอดขายรวม (บาท)']
            revenue_monthly = revenue_monthly.sort_values(by='ปี-เดือน', ascending=False)
            
            st.dataframe(revenue_monthly, use_container_width=True)
            
            # ปุ่มดาวน์โหลดรายงานสรุปยอดขายรายเดือน
            csv_summary = revenue_monthly.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 ดาวน์โหลดรายงานสรุปยอดขายรายเดือน (CSV)",
                data=csv_summary,
                file_name=f"monthly_revenue_summary_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
        else:
            st.info("ยังไม่มีข้อมูลการจองที่ยืนยันแล้วสำหรับนำมาสรุปยอดขาย")
            
        st.divider()
        
        # --- ข้อมูลการจองทั้งหมดเดิม ---
        st.subheader("📋 ประวัติการจองทั้งหมดในระบบ")
        st.dataframe(df_exp, use_container_width=True)
        
        csv_data = df_exp.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 ดาวน์โหลดข้อมูลการจองทั้งหมด (CSV File)",
            data=csv_data,
            file_name=f"jhouse_bookings_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            type="primary"
        )
