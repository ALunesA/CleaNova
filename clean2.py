import re
import urllib.parse
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

FILE = Path("complaints.csv")

COLUMNS = [
    "ID",
    "Reporter",
    "Location",
    "Waste Type",
    "Segregation",
    "Priority",
    "Description",
    "Photo URL",
    "Status",
    "Reported At",
    "Last Updated",
]

STATUSES = ["Pending", "In Progress", "Resolved"]
WASTE_TYPES = [
    "Household waste",
    "Plastic waste",
    "Construction waste",
    "E-waste",
    "Organic waste",
        "Other",
]
SEGREGATION_BINS = [
    "Green bin-wet waste",
    "Blue bin-Dry waste",
    "Yellow bin-biomedical waste",
    "Red bin-hazardous waste",
    "Black bin-e-waste",
]
PRIORITIES = ["Low", "Medium", "High"]
STATUS_CHART_COLORS = {
    "Pending": "#e57373",
    "In Progress": "#ffe082",
    "Resolved": "#69f0ae",
}
WASTE_CHART_COLORS = {
    "Household waste": "#69f0ae",
    "Plastic waste": "#80d8ff",
    "Construction waste": "#4db6ac",
    "E-waste": "#a5d6a7",
    "Organic waste": "#1de9b6",
    "Other": "#c5e1a5",
}
SEGREGATION_CHART_COLORS = {
    "Green bin-wet waste": "#66bb6a",
    "Blue bin-Dry waste": "#64b5f6",
    "Yellow bin-biomedical waste": "#ffe082",
    "Red bin-hazardous waste": "#ef9a9a",
    "Black bin-e-waste": "#b0bec5",
}


def now_text():
    return datetime.now().strftime("%d-%m-%Y %H:%M")


def load_data():
    """Read complaints from CSV. If the file is missing, start empty."""
    if FILE.exists():
        data = pd.read_csv(FILE)

        # Older CSV files may not have the new columns yet.
        for column in COLUMNS:
            if column not in data.columns:
                data[column] = ""

        return data[COLUMNS]
    return pd.DataFrame(columns=COLUMNS)


def save_data(data):
    """Save the table so it stays after you close the app."""
    data.to_csv(FILE, index=False)


def next_id(data):
    """Give each complaint a unique number."""
    if data.empty:
        return 1
    return int(pd.to_numeric(data["ID"], errors="coerce").max()) + 1


def maps_url(location):
    """Google Maps search link for a typed area / landmark."""
    query = urllib.parse.quote_plus(str(location).strip())
    return f"https://www.google.com/maps/search/?api=1&query={query}"


def photo_display_url(url):
    """Turn a Google Drive share link into a viewable image URL when possible."""
    raw = str(url).strip()
    if not raw or raw.lower() in {"nan", "none"}:
        return None
    file_id = None
    match = re.search(r"/file/d/([a-zA-Z0-9_-]+)", raw)
    if match:
        file_id = match.group(1)
    elif "drive.google.com" in raw or "docs.google.com" in raw:
        match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", raw)
        if match:
            file_id = match.group(1)
    if file_id:
        return f"https://drive.google.com/thumbnail?id={file_id}&sz=w1000"
    return raw or None


def daily_counts(frame, status=None):
    """Simple sparkline values from report dates."""
    if frame.empty:
        return [0, 0]
    subset = frame if status is None else frame[frame["Status"] == status]
    if subset.empty:
        return [0, 0]
    dates = pd.to_datetime(subset["Reported At"], dayfirst=True, errors="coerce")
    values = dates.dt.date.value_counts().sort_index().tolist()
    if len(values) < 2:
        values = [0] + values
    return values


def themed_bar_chart(series, color_map):
    """Bar chart using faint colors from the CleaNova theme."""
    if series is None or series.empty:
        st.info("No data to chart yet.")
        return
    chart_df = series.rename_axis("label").reset_index(name="count")
    domain = [str(x) for x in chart_df["label"].tolist()]
    palette = [color_map.get(label, "#1de9b6") for label in domain]
    chart = (
        alt.Chart(chart_df)
        .mark_bar(cornerRadiusEnd=6, opacity=0.72)
        .encode(
            x=alt.X(
                "label:N",
                sort="-y",
                title=None,
                axis=alt.Axis(labelAngle=-20, labelColor="#d7fff0", tickColor="#163328"),
            ),
            y=alt.Y(
                "count:Q",
                title=None,
                axis=alt.Axis(
                    labelColor="#d7fff0",
                    gridColor="#163328",
                    tickColor="#163328",
                    domainColor="#163328",
                ),
            ),
            color=alt.Color(
                "label:N",
                scale=alt.Scale(domain=domain, range=palette),
                legend=None,
            ),
            tooltip=["label", "count"],
        )
        .properties(height=280)
        .configure_view(strokeOpacity=0, fill="#050505")
        .configure_axis(gridOpacity=0.35)
    )
    st.altair_chart(chart)


def current_status_html(status):
    status = str(status)
    colors = {
        "Resolved": ("#00c853", "rgba(0, 200, 83, 0.16)"),
        "In Progress": ("#ffd54f", "rgba(255, 213, 79, 0.16)"),
        "Pending": ("#ff5252", "rgba(255, 82, 82, 0.16)"),
    }
    text, bg = colors.get(status, ("#80d8ff", "rgba(128, 216, 255, 0.16)"))
    return (
        f'<span class="status-pill" style="color:{text};background:{bg};'
        f'border:1px solid {text};">{status}</span>'
    )


def duplicate_groups(frame):
    """Reports that share the same area and waste type."""
    if frame.empty or len(frame) < 2:
        return []
    groups = []
    seen = set()
    for _, row in frame.iterrows():
        rid = int(row["ID"])
        if rid in seen:
            continue
        waste = str(row["Waste Type"])
        location = row["Location"]
        match_ids = [rid]
        for _, other in frame.iterrows():
            oid = int(other["ID"])
            if oid == rid or oid in seen:
                continue
            if str(other["Waste Type"]) == waste and same_area(other["Location"], location):
                match_ids.append(oid)
        if len(match_ids) < 2:
            continue
        seen.update(match_ids)
        groups.append(frame[frame["ID"].astype(int).isin(match_ids)].sort_values("ID"))
    return groups


def show_map(location):
    """Show a Google Maps pin for the typed location (no extra API key)."""
    if not str(location).strip():
        st.caption("Type an area or landmark to drop a pin on the map.")
        return

    url = maps_url(location)
    embed_q = urllib.parse.quote_plus(str(location).strip())
    st.markdown(f"[Open this pin in Google Maps]({url})")
    components.iframe(
        f"https://maps.google.com/maps?q={embed_q}&z=15&output=embed",
        height=300,
    )


def same_area(saved_location, typed_area):
    """Treat two location texts as the same area / landmark."""
    saved = str(saved_location).strip().lower()
    typed = str(typed_area).strip().lower()
    if not saved or not typed:
        return False
    if typed in saved or saved in typed:
        return True
    words = [w for w in typed.replace(",", " ").split() if len(w) >= 3]
    return any(word in saved for word in words)


def emergency_box():
    st.markdown(
        """
        <div class="emergency">
            <div class="emergency-title">Emergency contact</div>
            <div>Email: <a href="mailto:cleannova@gmail.com">cleannova@gmail.com</a></div>
            <div>24x7 helpline: +91 98765 43210</div>
            <div>City waste control room: +91 91234 56789</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def nav_button(label, page_id):
    selected = st.session_state.page == page_id
    if st.button(
        label,
        use_container_width=True,
        type="primary" if selected else "secondary",
        key=f"nav_{page_id}",
    ):
        st.session_state.page = page_id
        st.rerun()


def status_badge(status):
    status = str(status)
    if status == "Resolved":
        st.badge("Resolved", icon=":material/check_circle:", color="green")
    elif status == "In Progress":
        st.badge("In Progress", icon=":material/sync:", color="blue")
    else:
        st.badge("Pending", icon=":material/schedule:", color="orange")


def report_cards(rows):
    if rows.empty:
        st.info("Nothing to show here yet.")
        return

    for _, row in rows.iterrows():
        with st.container(border=True):
            top, mid = st.columns([3, 1])
            with top:
                st.markdown(f"**#{int(row['ID'])} · {row['Location']}**")
                st.caption(
                    f"{row['Waste Type']}  •  {row['Priority']}  •  {row['Reporter']}  •  {row['Reported At']}"
                )
                if str(row["Description"]).strip():
                    st.write(row["Description"])
            with mid:
                status_badge(row["Status"])
                st.link_button(
                    "Pin on Maps",
                    maps_url(row["Location"]),
                    use_container_width=True,
                )


st.set_page_config(
    page_title="CleaNova",
    page_icon=":material/recycling:",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"],
    [data-testid="stMain"], [data-testid="stBottomBlockContainer"] {
        background-color: #000000;
    }
    [data-testid="stSidebar"] {
        background: #050505;
        border-right: 1px solid #163328;
    }
    .hero {
        background: linear-gradient(100deg, #00c853 0%, #1de9b6 45%, #80d8ff 100%);
        padding: 28px 32px;
        border-radius: 22px;
        margin: 4px 0 22px 0;
        color: #04140c;
        box-shadow: 0 12px 40px rgba(0, 200, 83, 0.18);
    }
    .hero h1 {
        font-size: 2.6rem;
        font-weight: 800;
        letter-spacing: -0.04em;
        margin: 0;
        color: #04140c;
    }
    .hero p {
        margin: 8px 0 0 0;
        font-size: 1.05rem;
        color: #08321c;
        font-weight: 500;
    }
    .emergency {
        margin-top: 28px;
        padding: 16px 18px;
        border-radius: 16px;
        border: 1px solid #1de9b6;
        background: linear-gradient(180deg, #07140e 0%, #000000 100%);
        color: #d7fff0;
    }
    .emergency-title {
        font-weight: 700;
        color: #80d8ff;
        margin-bottom: 6px;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        font-size: 0.82rem;
    }
    .emergency a {
        color: #80d8ff;
        text-decoration: none;
    }
    .status-pill {
        display: inline-block;
        padding: 6px 14px;
        border-radius: 999px;
        font-weight: 700;
        font-size: 0.92rem;
        letter-spacing: 0.02em;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if "page" not in st.session_state:
    st.session_state.page = "Your past reports"

data = load_data()

total = len(data)
pending = int((data["Status"] == "Pending").sum()) if total else 0
progress = int((data["Status"] == "In Progress").sum()) if total else 0
resolved = int((data["Status"] == "Resolved").sum()) if total else 0

with st.sidebar:
    st.markdown("### CleaNova")
    st.caption("Smart waste reporting")

    with st.expander("City tools", expanded=True):
        nav_button("Report Garbage", "Report Garbage")
        nav_button("Dashboard", "Dashboard")
        nav_button("Update / Delete", "Update / Delete")

    with st.expander("For you", expanded=True):
        nav_button("Your past reports", "Your past reports")
        nav_button("Recently in your area", "Recently in your area")

    with st.expander("Duplicate", expanded=False):
        groups = duplicate_groups(data)
        if not groups:
            st.caption("No duplicate problems found yet.")
        else:
            st.caption("Same area and waste type reported more than once.")
            for group in groups:
                ids = ", ".join(f"#{int(i)}" for i in group["ID"])
                sample = group.iloc[0]
                st.markdown(
                    f"**{sample['Waste Type']}** · {sample['Location']}  \n"
                    f"{ids} · {len(group)} reports"
                )

    st.divider()
    st.markdown("**Who you are**")
    my_name = st.text_input("Your name", placeholder="Used to find your past reports")
    my_area = st.text_input(
        "Your area / landmark",
        placeholder="Example: College gate, Sector 21",
    )
    if my_area.strip():
        st.caption("Map preview of your area")
        show_map(my_area)

st.markdown(
    """
    <div class="hero">
        <h1>CleaNova</h1>
        <p>Report it. Track it. Clean it. A faster way to keep your city liveable.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

def jump_dashboard(status_values):
    st.session_state.page = "Dashboard"
    st.session_state.dash_status = status_values
    if "dash_status_filter" in st.session_state:
        del st.session_state.dash_status_filter
    st.rerun()


pct = lambda n: f"{int(round((n / total) * 100))}%" if total else "0%"
m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric(
        "Total reports",
        total,
        delta="All complaints",
        delta_color="off",
        border=True,
        chart_data=daily_counts(data),
        chart_type="area",
        help="Click below to open every report on the dashboard.",
    )
    if st.button("View all", use_container_width=True, key="kpi_total"):
        jump_dashboard(STATUSES)
with m2:
    st.metric(
        "Pending",
        pending,
        delta=f"{pct(pending)} of all",
        delta_color="red",
        border=True,
        chart_data=daily_counts(data, "Pending"),
        chart_type="bar",
        help="Reports still waiting to be picked up.",
    )
    if st.button("View pending", use_container_width=True, key="kpi_pending"):
        jump_dashboard(["Pending"])
with m3:
    st.metric(
        "In Progress",
        progress,
        delta=f"{pct(progress)} of all",
        delta_color="yellow",
        border=True,
        chart_data=daily_counts(data, "In Progress"),
        chart_type="bar",
        help="Reports currently being worked on.",
    )
    if st.button("View in progress", use_container_width=True, key="kpi_progress"):
        jump_dashboard(["In Progress"])
with m4:
    st.metric(
        "Resolved",
        resolved,
        delta=f"{pct(resolved)} of all",
        delta_color="green",
        border=True,
        chart_data=daily_counts(data, "Resolved"),
        chart_type="area",
        help="Reports that have been cleaned up.",
    )
    if st.button("View resolved", use_container_width=True, key="kpi_resolved"):
        jump_dashboard(["Resolved"])

page = st.session_state.page

if page == "Report Garbage":
    st.subheader("Report a waste problem")
    st.write("Drop a pin with the same area / landmark you type below. Your report is saved in `complaints.csv`.")

    location = st.text_input("Location (area / street / landmark)")
    show_map(location)

    with st.form("complaint_form", clear_on_submit=True):
        left, right = st.columns(2)
        with left:
            reporter = st.text_input("Your name", value=my_name)
            waste = st.selectbox("Type of waste", WASTE_TYPES)
            segregation = st.selectbox("Waste Segregation Category", SEGREGATION_BINS)
        with right:
            priority = st.selectbox("Priority", PRIORITIES, index=1)
            description = st.text_area(
                "Describe the problem",
                placeholder="Example: Overflowing bin near the bus stop.",
            )
            photo = st.text_input(
                "Photo URL (Google Drive or image link)",
                placeholder="https://drive.google.com/file/d/.../view",
            )
            st.caption("Upload a photo to Google Drive, share with anyone who has the link, then paste that URL.")
        submitted = st.form_submit_button("Submit Complaint", type="primary")

        if submitted:
            if not location.strip():
                st.error("Please enter a location.")
            elif not description.strip():
                st.error("Please describe the problem.")
            else:
                new_id = next_id(data)
                time_now = now_text()
                complaint = pd.DataFrame([{
                    "ID": new_id,
                    "Reporter": reporter.strip() or "Anonymous",
                    "Location": location.strip(),
                    "Waste Type": waste,
                    "Segregation": segregation,
                    "Priority": priority,
                    "Description": description.strip(),
                    "Photo URL": photo.strip(),
                    "Status": "Pending",
                    "Reported At": time_now,
                    "Last Updated": time_now,
                }])
                updated = pd.concat([data, complaint], ignore_index=True)
                save_data(updated)
                st.success(f"Complaint #{new_id} submitted. Thank you!")
                st.rerun()

    emergency_box()

elif page == "Dashboard":
    st.subheader("All complaints")

    if data.empty:
        st.info("No complaints yet. Open **Report Garbage** and submit the first one.")
    else:
        search = st.text_input("Search by location or description")
        if "dash_status" not in st.session_state:
            st.session_state.dash_status = STATUSES
        f1, f2, f3 = st.columns(3)
        with f1:
            status_filter = st.multiselect(
                "Status",
                STATUSES,
                default=st.session_state.dash_status,
                key="dash_status_filter",
            )
        with f2:
            waste_filter = st.multiselect("Waste type", WASTE_TYPES, default=WASTE_TYPES)
        with f3:
            priority_filter = st.multiselect("Priority", PRIORITIES, default=PRIORITIES)

        view = data.copy()
        view = view[view["Status"].isin(status_filter)]
        view = view[view["Waste Type"].isin(waste_filter)]
        view = view[view["Priority"].isin(priority_filter)]

        if search.strip():
            text = search.strip().lower()
            location_match = view["Location"].astype(str).str.lower().str.contains(text, na=False)
            description_match = view["Description"].astype(str).str.lower().str.contains(text, na=False)
            view = view[location_match | description_match]

        table = view.copy()
        table["Google Maps"] = table["Location"].astype(str).map(maps_url)
        table["Photo URL"] = table["Photo URL"].map(
            lambda u: str(u).strip() if str(u).strip() and str(u).strip().lower() not in {"nan", "none"} else None
        )
        table["Photo"] = table["Photo URL"].map(lambda u: photo_display_url(u) if u else None)

        st.write(f"Showing **{len(view)}** of **{total}** complaints.")
        st.dataframe(
            table,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Google Maps": st.column_config.LinkColumn("Google Maps", display_text="Open pin"),
                "Photo URL": st.column_config.LinkColumn("Photo URL", display_text="Open photo"),
                "Photo": st.column_config.ImageColumn("Photo"),
            },
        )

        csv_bytes = view.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download filtered CSV",
            data=csv_bytes,
            file_name="cleannova_complaints.csv",
            mime="text/csv",
        )

        st.subheader("Quick charts")
        chart1, chart2 = st.columns(2)
        with chart1:
            st.write("Complaints by status")
            themed_bar_chart(data["Status"].value_counts(), STATUS_CHART_COLORS)
        with chart2:
            st.write("Complaints by waste type")
            themed_bar_chart(data["Waste Type"].value_counts(), WASTE_CHART_COLORS)
        chart3, _ = st.columns(2)
        with chart3:
            st.write("Complaints by waste segregation")
            segregation_counts = data["Segregation"].astype(str).str.strip()
            segregation_counts = segregation_counts[~segregation_counts.isin(["", "nan", "None", "none"])]
            themed_bar_chart(segregation_counts.value_counts(), SEGREGATION_CHART_COLORS)

    emergency_box()

elif page == "Update / Delete":
    st.subheader("Update or delete a complaint")

    if data.empty:
        st.info("Nothing to manage yet.")
    else:
        ids = data["ID"].astype(int).tolist()
        selected_id = st.selectbox("Choose complaint ID", ids)
        row = data.loc[data["ID"].astype(int) == selected_id].iloc[0]

        st.write(
            f"**Location:** {row['Location']}  \n"
            f"**Waste:** {row['Waste Type']}  \n"
            f"**Priority:** {row['Priority']}"
        )
        st.markdown(
            "**Current status:** " + current_status_html(row["Status"]),
            unsafe_allow_html=True,
        )
        if str(row["Description"]).strip():
            st.write(f"**Description:** {row['Description']}")

        show_map(row["Location"])

        current_status = str(row["Status"])
        new_status = st.pills(
            "New status",
            STATUSES,
            default=current_status,
            selection_mode="single",
            key=f"new_status_{selected_id}",
            help="Pick a status. The colour preview updates immediately.",
        )
        preview = new_status or current_status
        st.markdown(
            "**Status preview:** " + current_status_html(preview),
            unsafe_allow_html=True,
        )
        if st.button("Update Status", type="primary"):
            chosen = new_status or current_status
            data.loc[data["ID"].astype(int) == selected_id, "Status"] = chosen
            data.loc[data["ID"].astype(int) == selected_id, "Last Updated"] = now_text()
            save_data(data)
            st.success(f"Complaint #{selected_id} is now **{chosen}**.")
            st.rerun()

        st.warning("Delete is permanent. Use it only for mistakes.")
        if st.button("Delete this complaint"):
            data = data[data["ID"].astype(int) != selected_id]
            save_data(data)
            st.success(f"Complaint #{selected_id} deleted.")
            st.rerun()

    emergency_box()

elif page == "Your past reports":
    st.subheader("Your past reports")
    st.write("Type your name in the sidebar. We match it with the **Reporter** field from older submissions.")

    if not str(my_name).strip():
        st.info("Enter your name in the left sidebar to see reports you submitted.")
    else:
        mine = data[data["Reporter"].astype(str).str.strip().str.lower() == my_name.strip().lower()]
        mine = mine.sort_values("ID", ascending=False) if not mine.empty else mine
        st.write(f"**{len(mine)}** report(s) found for **{my_name.strip()}**.")
        report_cards(mine)

    emergency_box()

else:
    st.subheader("Recently reported problems in your area")
    st.write(
        "Type your area or landmark in the sidebar. Reports with the same place in **Location** show up here."
    )

    if not str(my_area).strip():
        st.info("Enter your area / landmark in the left sidebar to see nearby reports.")
    else:
        mask = data["Location"].apply(lambda loc: same_area(loc, my_area))
        nearby = data[mask].copy()
        if not nearby.empty:
            nearby = nearby.sort_values("ID", ascending=False).head(12)
        st.write(f"Matching **{my_area.strip()}** · showing newest first.")
        report_cards(nearby)
        show_map(my_area)

    emergency_box()
