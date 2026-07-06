import sys
import logging
sys.modules['asyncio.logger'] = logging.getLogger('asyncio')
import asyncio
import sys
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date as dt_date
import os

# שם קובץ בסיס הנתונים
db_file = 'learning_center.db'

# חיבור לבסיס הנתונים (יוצר אותו אם הוא לא קיים)
conn = sqlite3.connect(db_file, check_same_thread=False)
c = conn.cursor()

# יצירת טבלת משתמשים
c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        role TEXT,
        credits INTEGER DEFAULT 0
    )
''')

# יצירת טבלת מועדים
c.execute('''
    CREATE TABLE IF NOT EXISTS center_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        time TEXT,
        UNIQUE(date, time)
    )
''')

# יצירת טבלת הרשמות
c.execute('''
    CREATE TABLE IF NOT EXISTS registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        slot_id INTEGER,
        reg_type TEXT DEFAULT 'כרטיסייה', 
        status TEXT DEFAULT 'ממתין לאישור בבוקר המפגש', 
        UNIQUE(username, slot_id)
    )
''')
conn.commit()

# --- שדרוג אוטומטי ובטוח של בסיס הנתונים למניעת קריסות ווינדוס ---
try:
    c.execute("SELECT reg_type FROM registrations LIMIT 1")
except sqlite3.OperationalError:
    c.execute("ALTER TABLE registrations ADD COLUMN reg_type TEXT DEFAULT 'כרטיסייה'")
    conn.commit()

try:
    c.execute("SELECT status FROM registrations LIMIT 1")
except sqlite3.OperationalError:
    c.execute("ALTER TABLE registrations ADD COLUMN status TEXT DEFAULT 'ממתין לאישור בבוקר המפגש'")
    conn.commit()

# אתחול משתני חיבור (Session State)
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    st.session_state['username'] = ""
    st.session_state['role'] = ""

st.title("🏫 מערכת ניהול מרכז למידה")

# --- מסך התחברות / יצירת חשבון ---
if not st.session_state['logged_in']:
    auth_mode = st.radio("בחר פעולה:", ["התחברות", "יצירת חשבון חדש"])
    username = st.text_input("שם משתמש:")
    password = st.text_input("סיסמה:", type="password")

    if auth_mode == "יצירת חשבון חדש":
        role = st.selectbox("סוג חשבון:", ["תלמיד", "מורה"])
        if st.button("הרשם למערכת"):
            if username.strip() == "" or password.strip() == "":
                st.error("נא למלא את כל השדות.")
            else:
                role_db = "teacher" if role == "מורה" else "student"
                try:
                    c.execute("INSERT INTO users (username, password, role, credits) VALUES (?, ?, ?, ?)",
                              (username, password, role_db, 0))
                    conn.commit()
                    st.success("החשבון נוצר בהצלחה! עבור למסך התחברות.")
                except sqlite3.IntegrityError:
                    st.error("שם המשתמש כבר קיים במערכת.")

    elif auth_mode == "התחברות":
        if st.button("התחבר"):
            c.execute("SELECT password, role FROM users WHERE username=?", (username,))
            user = c.fetchone()
            if user and user[0] == password:
                st.session_state['logged_in'] = True
                st.session_state['username'] = username
                st.session_state['role'] = user[1]
                st.success(f"ברוך הבא, {username}!")
                st.rerun()
            else:
                st.error("שם משתמש או סיסמה שגויים.")

# --- מסכים לאחר התחברות ---
else:
    st.sidebar.write(f"👋 מחובר בתור: **{st.session_state['username']}**")
    if st.sidebar.button("התנתק מהחשבון"):
        st.session_state.clear()
        st.rerun()

    # --- ממשק מורה ---
    if st.session_state['role'] == 'teacher':
        st.header("⚙️ לוח ניהול למורה")

        st.subheader("💳 חידוש כרטיסיות (תשלום ב-Bit)")
        c.execute("SELECT username, credits FROM users WHERE role='student'")
        students = c.fetchall()
        if students:
            student_list = {f"{row[0]} (יתרה נוכחית: {row[1]} כניסות)": row[0] for row in students}
            selected_student = st.selectbox("בחר תלמיד ששילם ב-Bit על כרטיסייה:", list(student_list.keys()))
            if st.button("➕ אשר תשלום והוסף 10 כניסות", type="primary"):
                student_username = student_list[selected_student]
                c.execute("UPDATE users SET credits = credits + 10 WHERE username=?", (student_username,))
                conn.commit()
                st.success(f"עודכן! התווספו 10 כניסות ל-{student_username}.")
                st.rerun()

        st.write("---")
        st.subheader("🗓️ פתיחת מועד במרכז")
        date_input = st.date_input("בחר תאריך", min_value=datetime.today())
        time_input = st.time_input("בחר שעה")
        if st.button("פתח את המרכז במועד זה"):
            date_str = date_input.strftime("%Y-%m-%d")
            time_str = time_input.strftime("%H:%M")
            try:
                c.execute("INSERT INTO center_slots (date, time) VALUES (?, ?)", (date_str, time_str))
                conn.commit()
                st.success(f"המרכז נפתח ב-{date_str} בשעה {time_str}!")
            except sqlite3.IntegrityError:
                st.error("מועד זה כבר קיים.")

        st.write("---")
        st.subheader("📋 רשימת תלמידים רשומים ומצב אישורם")
        df_regs = pd.read_sql_query('''
            SELECT center_slots.date as 'תאריך', center_slots.time as 'שעה', 
                   registrations.username as 'שם התלמיד', registrations.reg_type as 'סוג רישום',
                   registrations.status as 'סטטוס אישור הגעה'
            FROM registrations
            JOIN center_slots ON registrations.slot_id = center_slots.id
            ORDER BY center_slots.date, center_slots.time
        ''', conn)
        if not df_regs.empty:
            st.dataframe(df_regs, use_container_width=True)
        else:
            st.info("אין עדיין תלמידים רשומים.")

    # --- ממשק תלמיד ---
    else:
        st.header("🎓 אזור אישי לתלמיד")

        c.execute("SELECT credits FROM users WHERE username=?", (st.session_state['username'],))
        current_credits = c.fetchone()[0]

        st.metric(label="💳 יתרת כניסות בכרטיסייה שלך:", value=f"{current_credits} כניסות")

        with st.expander("🛒 קניית כרטיסייה חדשה (10 כניסות) - 600 ש\"ח"):
            st.write("### 📱 הוראות לתשלום עבור כרטיסייה:")
            st.write("1. שלח תשלום על סך **600 ש\"ח** למספר הטלפון: **0522664580** (איתם).")
            st.write("2. בסיבת ההעברה בביט, רשום: **כרטיסייה - " + st.session_state['username'] + "**.")
            st.link_button("פתח אפליקציית Bit 📱", "https://www.bitpay.co.il/")

        # ------ חלק א': אישור הגעה סופי בבוקר המפגש ------
        st.write("---")
        st.subheader("🔔 אישורי הגעה להיום")

        today_str = dt_date.today().strftime("%Y-%m-%d")

        c.execute('''
            SELECT registrations.id, center_slots.time, registrations.reg_type
            FROM registrations
            JOIN center_slots ON registrations.slot_id = center_slots.id
            WHERE registrations.username = ? AND center_slots.date = ? AND registrations.status = 'ממתין לאישור בבוקר המפגש'
        ''', (st.session_state['username'], today_str))
        pending_today = c.fetchall()

        if pending_today:
            st.info("📅 יש לך מפגש היום! אנא אשר הגעה סופית כדי לשמור על מקומך:")
            for reg_id, slot_time, reg_type in pending_today:
                col1, col2 = st.columns([3, 1])
                col1.write(f"⏰ מפגש היום בשעה **{slot_time}** ({reg_type})")

                if col2.button("אשר הגעה סופית ✅", key=f"confirm_{reg_id}"):
                    if reg_type == 'כרטיסייה' and current_credits < 1:
                        st.error("אין לך מספיק כניסות בכרטיסייה! אנא קנה כרטיסייה או שנה סוג רישום.")
                    else:
                        if reg_type == 'כרטיסייה':
                            c.execute("UPDATE users SET credits = credits - 1 WHERE username=?",
                                      (st.session_state['username'],))

                        c.execute("UPDATE registrations SET status = 'מאושר סופית' WHERE id=?", (reg_id,))
                        conn.commit()
                        st.success("הגעתך אושרה סופית! תהנה במרכז הלמידה.")
                        st.rerun()
        else:
            st.write("אין מפגשים הדורשים אישור מיידי להיום.")

        # ------ חלק ב': הרשמה מראש למועדים עתידיים ------
        st.write("---")
        st.subheader("📅 הרשמה מראש למועדי המרכז")

        c.execute('''
            SELECT id, date, time FROM center_slots 
            WHERE id NOT IN (SELECT slot_id FROM registrations WHERE username=?)
            ORDER BY date, time
        ''', (st.session_state['username'],))
        available_slots = c.fetchall()

        if available_slots:
            slot_options = {f"{datetime.strptime(slot[1], '%Y-%m-%d').strftime('%d/%m')} בשעה {slot[2]}": slot[0] for
                            slot in available_slots}
            selected_option = st.selectbox("בחר מועד להגעה:", list(slot_options.keys()))

            payment_method = st.radio("בחר אופן תשלום למפגש זה (החיוב יתבצע רק בבוקר המפגש):", [
                "רישום על חשבון כרטיסייה (מוריד 1 בבוקר המפגש)",
                "מפגש בודד ב-Bit (עלות: 140 ש\"ח בבוקר המפגש)"
            ], key="pay_radio")

            if "מפגש בודד" in payment_method:
                st.warning("⚠️ שים לב: בבוקר המפגש תצטרך להעביר **140 ש\"ח** ב-Bit למספר **0522664580**.")

            if st.button("הרשם מראש למועד זה", type="primary"):
                slot_id = slot_options[selected_option]
                reg_type_db = 'כרטיסייה' if "כרטיסייה" in payment_method else 'מפגש בודד'

                c.execute(
                    "INSERT INTO registrations (username, slot_id, reg_type, status) VALUES (?, ?, ?, 'ממתין לאישור בבוקר המפגש')",
                    (st.session_state['username'], slot_id, reg_type_db))
                conn.commit()
                st.success(f"נרשמת מראש בהצלחה! זכור להיכנס לאפליקציה בבוקר המפגש בשביל לאשר הגעה סופית.")
                st.rerun()
        else:
            st.info("אין מועדים פנויים כרגע.")

        # הצגת המועדים המתוכננים של התלמיד
        st.write("---")
        st.subheader("✅ המועדים המתוכננים שלך")
        df_my_slots = pd.read_sql_query('''
            SELECT center_slots.date as 'תאריך', center_slots.time as 'שעה', 
                   registrations.reg_type as 'סוג רישום', registrations.status as 'סטטוס'
            FROM registrations
            JOIN center_slots ON registrations.slot_id = center_slots.id
            WHERE registrations.username = ?
            ORDER BY center_slots.date, center_slots.time
        ''', conn, params=(st.session_state['username'],))
        if not df_my_slots.empty:
            st.table(df_my_slots)
