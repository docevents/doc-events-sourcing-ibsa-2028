import streamlit as st
import os
import pandas as pd
import re

st.set_page_config(page_title="Doc Events – Hotel Extractor", layout="wide")

st.markdown("""
<style>
    .doc-header {
        background-color: #323438; padding: 18px 32px;
        border-bottom: 4px solid #FBBD1E; margin-bottom: 24px; border-radius: 6px;
    }
    .doc-header h1 { color: #FBBD1E; margin: 0; font-size: 28px; font-family: Lato, sans-serif; }
    .doc-header p  { color: #B4ABA1; margin: 4px 0 0 0; font-size: 14px; }
    .section-title {
        font-size: 18px; font-weight: 700; color: #323438;
        border-bottom: 2px solid #FBBD1E; padding-bottom: 6px; margin: 24px 0 16px 0;
    }
    .calc-box {
        background: #fff8e1; border: 1px solid #FBBD1E;
        border-radius: 6px; padding: 10px 14px; margin-top: 8px; font-size: 13px; line-height: 1.8;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="doc-header">
    <h1>Doc Events &nbsp;|&nbsp; Hotel Extractor</h1>
    <p>Project 1 — Upload a Cvent report to review and select hotels for your proposal</p>
</div>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def find_row(df, label, exact=False):
    for i, val in enumerate(df.iloc[:, 0]):
        s = str(val).strip()
        if exact and s == label: return i
        elif not exact and label.lower() in s.lower(): return i
    return None

def get_val(df, row_idx, col_idx):
    if row_idx is None: return ""
    try:
        v = df.iloc[row_idx, col_idx]
        return "" if pd.isna(v) else str(v).strip()
    except: return ""

def short_desc(text, max_chars=220):
    text = re.sub(r'\s+', ' ', text.replace('\n', ' ')).strip()
    return text[:max_chars] + "…" if len(text) > max_chars else text

def parse_address(raw):
    return raw.replace('\\n', ', ').replace('\n', ', ').strip()

def availability_icon(val):
    v = val.lower()
    if "not available" in v: return "🔴"
    if "1st option"    in v: return "🟢"
    if "2nd option"    in v: return "🟡"
    if "limitation"    in v: return "🟠"
    return "⚪"

def parse_single_double_rates(add_det, rate_lo, is_per_person):
    """
    Extract explicit single and double room rates from additional details.
    Returns (single_rate, double_rate) as per-room amounts.
    Falls back to rate_lo for double if not found.
    """
    if not add_det or add_det.lower() == "nan":
        double = rate_lo * 2 if is_per_person else rate_lo
        return double, double  # same for both if no detail

    text = add_det
    single, double = 0.0, 0.0

    # Pattern: "SGL 594" or "SGL $594" or "single ... $594"
    sgl_m = re.search(r'(?:SGL|Single Occ[^$\d]*)\$?\s*([\d,]+)', text, re.IGNORECASE)
    if sgl_m:
        single = float(sgl_m.group(1).replace(",", ""))

    # Pattern: "DBL 330" or "$330 pp ... double" → multiply if per person
    dbl_m = re.search(r'(?:DBL|Double Occ[^$\d]*)\$?\s*([\d,]+)', text, re.IGNORECASE)
    if dbl_m:
        dbl_val = float(dbl_m.group(1).replace(",", ""))
        double = dbl_val * 2 if is_per_person else dbl_val

    # Pattern: "$556.00 ... double occupancy"
    if double == 0.0:
        dbl_m2 = re.search(r'\$([\d,]+\.?\d*)\s*USD[^.]*double occupancy', text, re.IGNORECASE)
        if dbl_m2:
            double = float(dbl_m2.group(1).replace(",", ""))

    # Pattern: "$474.00 ... single occupancy"
    if single == 0.0:
        sgl_m2 = re.search(r'\$([\d,]+\.?\d*)[^.]*single occupancy', text, re.IGNORECASE)
        if sgl_m2:
            single = float(sgl_m2.group(1).replace(",", ""))

    # Fallbacks
    if double == 0.0:
        double = rate_lo * 2 if is_per_person else rate_lo
    if single == 0.0:
        single = double  # default single = double if not found

    return single, double

def parse_rate(rate_str):
    """
    Returns (rate_low, rate_high, is_range, has_rate, display_str)
    Handles: '229.00 USD (48 rooms)', '359.00 USD - 659.00 USD (48 rooms)', '339', empty/nan
    """
    if not rate_str or str(rate_str).lower() == "nan":
        return 0.0, 0.0, False, False, ""
    
    rate_str = str(rate_str).strip()
    
    # Try to find USD format first
    nums = re.findall(r'([\d]+\.?\d*)\s*USD', rate_str.replace(',', ''))
    
    # If no USD found, try plain numbers (e.g., "339" or "339 - 450")
    if not nums:
        nums = re.findall(r'([\d]+\.?\d*)', rate_str.replace(',', ''))
    
    if len(nums) >= 2:
        lo, hi = float(nums[0]), float(nums[1])
        return lo, hi, True, True, f"${lo:.0f} – ${hi:.0f} / night"
    elif len(nums) == 1:
        v = float(nums[0])
        return v, v, False, True, f"${v:.0f} / night"
    return 0.0, 0.0, False, False, ""

def parse_single_double_rates(roh_rate, add_details, is_per_person):
    """
    Parse single and double room rates from additional details text.
    Returns (single_rate, double_rate) as per-room amounts.
    Falls back to ROH-based calculation if not found.
    """
    import re as _re
    det = str(add_details)

    # Xcaret-style: "SGL $680 per room" / "DBL $425 per person x 2= $850 per room"
    sgl_room = _re.search(r'SGL[^\n$]*\$([\d,]+)\s*per room', det)
    dbl_room = _re.search(r'per room[^\n]*in double[^\n]*\$([\d,]+)|'
                          r'DBL[^\n$]*\$([\d,]+)\s*per room|'
                          r'= \$([\d,]+)\s*per room.*double', det)

    # Paradisus Ocean View style: "Ocean View at $666 ... double ... $568 ... single"
    ocean_dbl = _re.search(r'Ocean View at \$([\d,]+)[^\n]*double', det)
    ocean_sgl_match = _re.search(r'Ocean View at[^\n]*and \$([\d,]+)[^\n]*single', det)

    # Generic: "single occupancy $XXX"
    gen_sgl = _re.search(r'single[^\n$]*\$([\d,]+)|\$([\d,]+)[^\n]*single occ', det, _re.IGNORECASE)
    gen_dbl = _re.search(r'double[^\n$]*\$([\d,]+)|\$([\d,]+)[^\n]*double occ', det, _re.IGNORECASE)

    def clean(m, group=1):
        if not m: return 0.0
        for g in range(1, 5):
            try:
                v = m.group(g)
                if v: return float(v.replace(',',''))
            except: pass
        return 0.0

    # Priority: Ocean View > explicit SGL/DBL room > generic > fallback
    if ocean_dbl:
        double_r = clean(ocean_dbl)
        single_r = clean(ocean_sgl_match) if ocean_sgl_match else double_r * 0.85
    elif sgl_room:
        single_r = clean(sgl_room)
        # Try to get double from "= $850 per room" pattern
        dbl_eq = _re.search(r'=\s*\$([\d,]+)\s*per room', det)
        double_r = clean(dbl_eq) if dbl_eq else (roh_rate * 2 if is_per_person else roh_rate)
    elif gen_sgl:
        single_r = clean(gen_sgl)
        double_r = clean(gen_dbl) if gen_dbl else (roh_rate * 2 if is_per_person else roh_rate)
    else:
        # Fallback: per-person hotels → single = rate×1, double = rate×2
        single_r = roh_rate if not is_per_person else roh_rate
        double_r = roh_rate * 2 if is_per_person else roh_rate

    return single_r, double_r

def parse_nights(nights_val, rate_str):
    if nights_val and str(nights_val).strip().isdigit():
        return int(nights_val)
    m = re.search(r'\((\d+)\s*rooms?\)', rate_str, re.IGNORECASE)
    return int(m.group(1)) if m else 0

def parse_resort_fee(fee_str):
    if not fee_str or fee_str.lower() == "nan": return 0.0, 0.0
    m1 = re.search(r'([\d.]+)\s*USD', fee_str)
    m2 = re.search(r'\+([\d.]+)%', fee_str)
    return (float(m1.group(1)) if m1 else 0.0), (float(m2.group(1)) / 100 if m2 else 0.0)

def parse_tax(tax_str):
    pct = sum(float(x) for x in re.findall(r'([\d.]+)%', tax_str))
    usd = sum(float(x) for x in re.findall(r'([\d.]+)\s*USD', tax_str))
    return pct / 100, usd

def calc_cost(rate, res_fee, res_tax, tax_pct, tax_fixed, nights):
    if rate == 0 or nights == 0: return 0.0
    nightly = (rate + res_fee * (1 + res_tax)) + tax_fixed
    return nightly * (1 + tax_pct) * nights


# Set default event details (no user input)
p1_event_name   = ""
p1_client_name  = ""
p1_attendees    = 0
p1_nights       = 0
p1_meeting_days = 0

# ── Load file from GitHub ──────────────────────────────────────────────────────
# Auto-load IBSA_2028.xlsx from GitHub
github_url = "https://raw.githubusercontent.com/docevents/doc-events-sourcing-ibsa-2028/main/IBSA_2028.xlsx"

with st.spinner("Loading hotel data…"):
    try:
        df = pd.read_excel(github_url, sheet_name=0, header=None)
    except Exception as e:
        st.error(f"Error loading file: {e}")
        st.stop()

# ── Row indices ───────────────────────────────────────────────────────────────
r_name         = find_row(df, "Venue Name",                             exact=True)
r_address      = find_row(df, "Venue Address",                          exact=True)
r_desc         = find_row(df, "Venue Description",                      exact=True)
r_proposed_date = find_row(df, "Proposed Date")
r_alt_date_1   = find_row(df, "Guest Room Dates (Alternate 1")
r_avail        = find_row(df, "Availability for Planner Preferred Date")
r_commission   = find_row(df, "Commission",                             exact=True)
r_tax_rooms    = find_row(df, "Guest Room Rates Applicable Tax")
r_room_rate    = find_row(df, "Guest Room Rates - Any (Run of House)", exact=False)
r_alt_room_rate_1 = find_row(df, "Guest Room Rates - Any (Run of House) (Alternate 1")
r_alt_room_rate_2 = find_row(df, "Guest Room Rates - Any (Run of House) (Alternate 2")
r_room_single  = find_row(df, "Guest Room Rates - Single (1 Bed)",      exact=True)
r_total_nights = find_row(df, "Total Guest Room Nights",                exact=True)
r_room_cost    = find_row(df, "Total Guest Room Cost",                  exact=True)
r_resort_fee   = find_row(df, "Resort Fee",                             exact=True)
r_add_tax      = find_row(df, "Additional Tax Information")
r_add_details  = find_row(df, "Additional Guest Room Details")
r_inc_tax      = find_row(df, "Guest Room Rates Include Tax",     exact=True)
r_all_inc_rate = find_row(df, "All Inclusive Rate",               exact=True)
r_fb_min       = find_row(df, "Total Food and Beverage Minimum")
r_fb_sc        = find_row(df, "Service Charge Estimated Cost")
r_fb_tax       = find_row(df, "Applicable Tax Estimated Cost")
r_meet_space   = find_row(df, "Total Meeting Space",                    exact=True)
r_meet_cost    = find_row(df, "Total Meeting Rooms Estimated Cost")
r_guest_rooms  = find_row(df, "Venue Guest Rooms",                      exact=True)
# F&B unit cost rows
r_fb_am_break  = find_row(df, "AM Break Estimated Cost")
r_fb_pm_break  = find_row(df, "PM Break Estimated Cost")
r_fb_cont_bkft = find_row(df, "Continental Breakfast Estimated Cost")
r_fb_buf_bkft  = find_row(df, "Buffet Breakfast Estimated Cost")
r_fb_pla_bkft  = find_row(df, "Plated Breakfast Estimated Cost")
r_fb_buf_lunch = find_row(df, "Buffet Lunch Estimated Cost")
r_fb_pla_lunch = find_row(df, "Plated Lunch Estimated Cost")
r_fb_buf_din   = find_row(df, "Buffet Dinner Estimated Cost")
r_fb_pla_din   = find_row(df, "Plated Dinner Estimated Cost")
r_fb_rec_food  = find_row(df, "Reception With Food Estimated Cost")
r_fb_rec_bev   = find_row(df, "Reception With Beverages Estimated Cost")
r_concessions  = find_row(df, "Offered Concessions/Contractual Requirements")

hotel_cols = [c for c in range(1, df.shape[1]) if get_val(df, r_name, c)]
if not hotel_cols:
    st.error("Could not find hotel data. Please check the file format.")
    st.stop()

# ── Build hotel list ──────────────────────────────────────────────────────────
hotels = []
for col in hotel_cols:
    # Extract dates and availability first to determine which rate to use
    proposed_date = get_val(df, r_proposed_date, col)
    alt_date_1 = get_val(df, r_alt_date_1, col)
    availability_status = get_val(df, r_avail, col).strip()
    
    # Determine if using alternate date
    using_alt_date = False
    if "not available" in availability_status.lower() and alt_date_1 and alt_date_1.lower() != "nan":
        dates_str = alt_date_1
        availability_status = "Available"
        using_alt_date = True
    else:
        dates_str = proposed_date
    
    # Select rate based on which date is available
    if using_alt_date:
        roh_str = get_val(df, r_alt_room_rate_1, col)
        # Fallback: if line 58 empty, try line 59
        if not roh_str or roh_str.lower() == "nan":
            roh_str = get_val(df, r_alt_room_rate_2, col)
    else:
        roh_str = get_val(df, r_room_rate, col)
    
    single_str = get_val(df, r_room_single,  col)
    add_det    = get_val(df, r_add_details,  col)
    tax_str    = get_val(df, r_tax_rooms,    col)
    resort_str = get_val(df, r_resort_fee,   col)
    nights_val = get_val(df, r_total_nights, col)

    # Use ROH rate first; fall back to single-bed rate
    def parse_fb_pp(row_idx):
        """Extract $/person from strings like '18.00 USD per person (+7.00% tax...)'"""
        v = get_val(df, row_idx, col)
        m = re.search(r'([\d.]+)\s*USD', v)
        return float(m.group(1)) if m else 0.0

    # Parse city/state from address
    raw_addr = get_val(df, r_address, col)
    addr_parts = [p.strip() for p in raw_addr.replace('\\n', ',').replace('\n', ',').split(',')]
    city  = addr_parts[1] if len(addr_parts) > 1 else ""
    state = addr_parts[2] if len(addr_parts) > 2 else ""

    # Check if tax is already included in the rate
    inc_tax_str = get_val(df, r_inc_tax, col).strip().lower()
    tax_included = inc_tax_str == "yes"

    # All-inclusive rate fallback (e.g. Hyatt Vivid)
    all_inc_str = get_val(df, r_all_inc_rate, col)

    rate_source = roh_str if (roh_str and roh_str.lower() != "nan") else single_str
    # Fall back to all-inclusive rate if no room rate
    if not rate_source or rate_source.lower() == "nan":
        rate_source = all_inc_str

    rate_lo, rate_hi, is_range, has_rate, rate_display = parse_rate(rate_source)

    # Detect per-person pricing from additional details
    add_lower = add_det.lower()
    is_per_person = any(phrase in add_lower for phrase in [
        "per person per night", "pp/pn", "per person, per night",
        "per person on", "per person based"
    ])
    # Per-room rate = rate × 2 for double occupancy
    rate_lo_room = rate_lo * 2 if is_per_person else rate_lo
    rate_hi_room = rate_hi * 2 if is_per_person else rate_hi
    rate_display_room = (f"${rate_lo_room:.0f} – ${rate_hi_room:.0f} / room/night"
                         if is_range else f"${rate_lo_room:.0f} / room/night") if has_rate else ""

    # Parse explicit single/double rates from additional details
    rate_single, rate_double = parse_single_double_rates(add_det, rate_lo, is_per_person)

    # Detect room type options from additional details
    # Look for Ocean View / Sunset View / Garden View mentions with rates
    room_type_options = []
    ocean_rate = 0.0
    ocean_rate_room = 0.0
    if "ocean view" in add_lower or "ocean" in add_lower:
        # Try to extract ocean view rate
        ocean_matches = re.findall(
            r'(?:ocean view)[^0-9]*[$]?([0-9,]+[.]?[0-9]*)', add_det, re.IGNORECASE)
        if ocean_matches:
            ocean_rate = float(ocean_matches[0].replace(",",""))
            ocean_rate_room = ocean_rate * 2 if is_per_person else ocean_rate
            room_type_options.append(f"Ocean View: ${ocean_rate:.0f}/pp" if is_per_person
                                     else f"Ocean View: ${ocean_rate:.0f}/room")
    if "sunset view" in add_lower or "garden view" in add_lower:
        room_type_options.append("Sunset/Garden View: (rate above)")
    has_room_type_choice = len(room_type_options) > 0

    # Parse specific single/double rates from additional details
    rate_single, rate_double = parse_single_double_rates(add_det, rate_lo, is_per_person)
    nights     = parse_nights(nights_val, rate_source)
    res_fee, res_tax = parse_resort_fee(resort_str)
    tax_pct, tax_fixed = parse_tax(tax_str)

    # For ranged rates show low-end cost estimate
    est_cost = calc_cost(rate_lo, res_fee, res_tax, tax_pct, tax_fixed, nights) if has_rate else 0.0
    est_cost_hi = calc_cost(rate_hi, res_fee, res_tax, tax_pct, tax_fixed, nights) if (has_rate and is_range) else 0.0

    # Comments: add_details stripped of boilerplate
    comments = short_desc(add_det, 300) if add_det and add_det.lower() != "nan" else ""

    hotels.append({
        "col":           col,
        "name":          get_val(df, r_name,       col),
        "address":       parse_address(get_val(df, r_address, col)),
        "description":   short_desc(get_val(df, r_desc, col)),
        "dates":         dates_str,
        "alt_dates":     alt_date_1,
        "availability":  availability_status,
        "commission":    get_val(df, r_commission,  col),
        "has_rate":      has_rate,
        "rate_lo":       rate_lo,
        "rate_hi":       rate_hi,
        "is_range":      is_range,
        "rate_display":  rate_display,
        "rate_source":   "Single/1-bed rate" if (not roh_str or roh_str.lower() == "nan") and single_str else "Run of House",
        "nights":        nights,
        "resort_fee":    res_fee,
        "resort_fee_str":resort_str,
        "resort_fee_tax":res_tax,
        "tax_pct":       tax_pct,
        "tax_fixed":     tax_fixed,
        "tax_str":       tax_str.replace("\\n", " | "),
        "add_tax":       get_val(df, r_add_tax,     col),
        "comments":      comments,
        "est_cost":      est_cost,
        "est_cost_hi":   est_cost_hi,
        "is_per_person":        is_per_person,
        "tax_included":         tax_included,
        "room_type_options":    room_type_options,
        "has_room_type_choice": has_room_type_choice,
        "ocean_rate":           ocean_rate,
        "ocean_rate_room":      ocean_rate_room,
        "rate_lo_room":  rate_lo_room,
        "rate_hi_room":  rate_hi_room,
        "rate_display_room": rate_display_room,
        "rate_single":   rate_single,
        "rate_double":   rate_double,
        "rate_single":   rate_single,
        "rate_double":   rate_double,
        "cvent_cost":    get_val(df, r_room_cost,   col),
        "fb_minimum":    get_val(df, r_fb_min,      col),
        "fb_service":    get_val(df, r_fb_sc,       col),
        "fb_tax":        get_val(df, r_fb_tax,      col),
        "meet_space":    get_val(df, r_meet_space,  col),
        "meet_cost":     get_val(df, r_meet_cost,   col),
        "guest_rooms":   get_val(df, r_guest_rooms, col),
        "city":          city,
        "state":         state,
        "concessions":   short_desc(get_val(df, r_concessions, col), 400),
        # F&B unit costs from Cvent ($/person)
        "fb_am_break":   parse_fb_pp(r_fb_am_break),
        "fb_pm_break":   parse_fb_pp(r_fb_pm_break),
        "fb_cont_bkft":  parse_fb_pp(r_fb_cont_bkft),
        "fb_buf_bkft":   parse_fb_pp(r_fb_buf_bkft),
        "fb_pla_bkft":   parse_fb_pp(r_fb_pla_bkft),
        "fb_buf_lunch":  parse_fb_pp(r_fb_buf_lunch),
        "fb_pla_lunch":  parse_fb_pp(r_fb_pla_lunch),
        "fb_buf_din":    parse_fb_pp(r_fb_buf_din),
        "fb_pla_din":    parse_fb_pp(r_fb_pla_din),
        "fb_rec_food":   parse_fb_pp(r_fb_rec_food),
        "fb_rec_bev":    parse_fb_pp(r_fb_rec_bev),
    })

# ── Event info ────────────────────────────────────────────────────────────────
event_name  = get_val(df, 0, 0)
event_dates = get_val(df, 1, 0).replace("Event Dates:", "").strip()
if event_name:
    c1, c2 = st.columns([2, 1])
    with c1: st.markdown(f"### 📋 {event_name}")
    with c2:
        if event_dates: st.markdown(f"**Dates:** {event_dates}")

st.markdown(f"**{len(hotels)} hotels found.** Select 3–4 for your proposal.")
st.divider()

# ── Filters ───────────────────────────────────────────────────────────────────
cf1, cf2 = st.columns([2, 1])
with cf1: search = st.text_input("🔍 Search by name or location", "")
with cf2:
    avail_filter = st.selectbox("Filter by availability",
        ["All", "1st option", "2nd option", "Available with limitations", "Not available"])

filtered = [
    h for h in hotels
    if (not search or search.lower() in h["name"].lower() or search.lower() in h["address"].lower())
    and (avail_filter == "All" or avail_filter.lower() in h["availability"].lower())
]

# Sort by State, then City
filtered = sorted(filtered, key=lambda h: (h.get("state", ""), h.get("city", "")))

st.markdown(f"*Showing {len(filtered)} of {len(hotels)} hotels*")

# ── Hotel cards ───────────────────────────────────────────────────────────────
if "selected" not in st.session_state:
    st.session_state.selected = set()
if "hidden" not in st.session_state:
    st.session_state.hidden = set()

st.markdown('<div class="section-title">Hotel Options</div>', unsafe_allow_html=True)
n_hidden = len(st.session_state.hidden)
hcol1, hcol2 = st.columns([3,1])
if n_hidden > 0:
    show_hidden = hcol2.toggle(f"Show {n_hidden} hidden hotel(s)", value=False, key="show_hidden")
    if hcol2.button("Unhide all", key="unhide_all"):
        st.session_state.hidden = set()
        st.rerun()
else:
    show_hidden = False
if "selected" not in st.session_state:
    st.session_state.selected = set()

# ── Select All / Deselect All ────────────────────────────────────────────────
st.markdown('<div class="section-title">🏨 Hotel Selection</div>', unsafe_allow_html=True)
all_hotel_cols = [h['col'] for h in filtered]

def toggle_select_all():
    if st.session_state.select_all_toggle:
        st.session_state.selected = set(all_hotel_cols)
    else:
        st.session_state.selected = set()

all_selected = len(st.session_state.selected) == len(all_hotel_cols) and len(all_hotel_cols) > 0
sa_col1, sa_col2 = st.columns([0.15, 0.85])
with sa_col1:
    st.checkbox("Select All", value=all_selected, key="select_all_toggle", on_change=toggle_select_all)

# Group hotels by state and display with headers
current_state = None
for h in filtered:
    # Show state header when state changes
    if h['state'] != current_state:
        current_state = h['state']
        st.markdown(f"### 🏨 {current_state.upper()}")
    
    is_hidden = h['col'] in st.session_state.hidden

    # Show collapsed stub for hidden hotels (only if toggle is on)
    if is_hidden:
        if show_hidden:
            sc1, sc2, sc3 = st.columns([0.5, 3, 0.5])
            sc2.caption(f"👁 Hidden: {h['name']}")
            if sc3.button("Show", key=f"unhide_{h['col']}"):
                st.session_state.hidden.discard(h['col'])
                st.rerun()
        continue

    c_chk, c_card = st.columns([0.05, 0.95])
    with c_chk:
        def make_hotel_callback(col):
            def callback():
                if st.session_state.get(f"chk_{col}"):
                    st.session_state.selected.add(col)
                else:
                    st.session_state.selected.discard(col)
            return callback
        
        st.checkbox("", 
                   key=f"chk_{h['col']}",
                   value=(h['col'] in st.session_state.selected),
                   on_change=make_hotel_callback(h['col']))

    with c_card:
        with st.container(border=True):
            # Name + location + hide button
            name_col, hide_col = st.columns([5, 1])
            name_col.markdown(f"#### {h['name']}")
            if hide_col.button("Hide 👁", key=f"hide_{h['col']}", help="Hide this hotel from view"):
                st.session_state.hidden.add(h['col'])
                st.session_state.selected.discard(h['col'])
                st.rerun()
            st.caption(f"📍 {h['address']}")

            # Availability + room info badges
            badges = [
                f"{availability_icon(h['availability'])} {h['availability']}",
                f"🏨 {h['guest_rooms']} rooms",
                f"📐 {h['meet_space']}",
            ]
            if h["resort_fee"] > 0:
                badges.append(f"🏖 Resort fee: ${h['resort_fee']:.0f}/night")
            st.markdown("&nbsp;&nbsp;|&nbsp;&nbsp;".join(f"**{b}**" for b in badges))
            
            # Show dates for all hotels
            dates_display = []
            if h["dates"] and h["dates"].lower() != "nan":
                dates_display.append(f"**Preferred:** {h['dates']}")
            if h["alt_dates"] and h["alt_dates"].lower() != "nan" and h["alt_dates"] != h["dates"]:
                dates_display.append(f"**Alternate:** {h['alt_dates']}")
            
            if dates_display:
                st.info(f"📅 " + " | ".join(dates_display))

            st.write("")

            # Rate display (smaller font, same as hotel name)
            if not h["has_rate"]:
                st.warning("⚠️ Rate not provided by this hotel")
            else:
                m1, m2, m3 = st.columns(3)
                # Show $/pp and $/room for per-person hotels
                if h["is_per_person"]:
                    m1.markdown(f"**Rate ($/pp/night)**<br>{h['rate_display']}", unsafe_allow_html=True)
                    m2.markdown(f"**Rate ($/room/night)**<br>{h['rate_display_room']}", unsafe_allow_html=True)
                else:
                    m1.markdown(f"**Room Rate**<br>{h['rate_display']}", unsafe_allow_html=True)
                    m2.markdown(f"**Resort Fee**<br>${h['resort_fee']:.0f}/night" if h["resort_fee"] > 0 else "**Resort Fee**<br>—", unsafe_allow_html=True)
                if h["is_range"]:
                    m3.markdown(f"**Est. Accommodation**<br>${h['est_cost']:,.0f} – ${h['est_cost_hi']:,.0f}", unsafe_allow_html=True)
                    st.info(f"ℹ️ Rate range: **{h['rate_display']}** ({h['rate_source']}). "
                            f"Estimated accommodation shown for low and high end of range.")
                else:
                    m3.markdown(f"**Est. Accommodation**<br>${h['est_cost']:,.0f}", unsafe_allow_html=True)
                # Per-person note
                if h["is_per_person"]:
                    st.info(f"ℹ️ Rate is **per person/night** (double occupancy). "
                            f"Per-room rate: **{h['rate_display_room']}**")
                if h["has_room_type_choice"]:
                    opts = " | ".join(h["room_type_options"])
                    st.info(f"🏨 Room type options: {opts}")
                    if h["ocean_rate"] > 0:
                        ocean_pp = h["ocean_rate_room"]
                        st.info(f"🌊 Ocean View per-room rate: **${ocean_pp:,.0f}/night**")
                # Tax included note
                if h["tax_included"]:
                    st.success("✅ Tax & gratuities already included in room rate")
                if h["rate_source"] == "Single/1-bed rate":
                    st.info("ℹ️ Rate shown is Single/1-bed — no Run of House rate provided.")

            # Comments from hotel
            if h["comments"]:
                st.markdown(f"💬 *{h['comments']}*")

            # Short description
            st.markdown(f"*{h['description']}*")

            # Expander
            with st.expander("View full details & cost breakdown"):
                d1, d2, d3 = st.columns(3)

                with d1:
                    st.markdown("**🛏 Accommodation**")
                    if h["has_rate"]:
                        st.markdown(f"- Rate: **{h['rate_display']}** ({h['rate_source']})")
                    else:
                        st.markdown("- Rate: **Not provided**")
                    if h["resort_fee"] > 0:
                        st.markdown(f"- Resort fee: **${h['resort_fee']:.2f}/night** (+{h['resort_fee_tax']*100:.0f}% tax)")
                    st.markdown(f"- Total room nights: **{h['nights']}**")
                    st.markdown(f"- Room taxes: {h['tax_str'] or '—'}")
                    if h["add_tax"]:
                        st.markdown(f"- ℹ️ *{short_desc(h['add_tax'], 180)}*")

                    if h["has_rate"]:
                        res_with_tax = h['resort_fee'] * (1 + h['resort_fee_tax'])
                        nightly_lo   = h['rate_lo'] + res_with_tax + h['tax_fixed']
                        nightly_hi   = h['rate_hi'] + res_with_tax + h['tax_fixed']
                        if h["is_range"]:
                            st.markdown(f"""
<div class="calc-box">
<b>📊 Cost Calculation (range)</b><br>
Low rate: ${h['rate_lo']:.2f} &nbsp;|&nbsp; High rate: ${h['rate_hi']:.2f}<br>
+ Resort fee + tax: ${res_with_tax:.2f}<br>
+ Fixed tax/night: ${h['tax_fixed']:.2f}<br>
× % tax: {h['tax_pct']*100:.1f}%<br>
× {h['nights']} nights<br>
<b>= Est. Total: ${h['est_cost']:,.2f} – ${h['est_cost_hi']:,.2f}</b>
</div>""", unsafe_allow_html=True)
                        else:
                            st.markdown(f"""
<div class="calc-box">
<b>📊 Cost Calculation</b><br>
Room rate: ${h['rate_lo']:.2f}<br>
+ Resort fee + tax: ${res_with_tax:.2f}<br>
+ Fixed tax/night: ${h['tax_fixed']:.2f}<br>
= Nightly subtotal: ${nightly_lo:.2f}<br>
× % tax: {h['tax_pct']*100:.1f}%<br>
× {h['nights']} nights<br>
<b>= Est. Total: ${h['est_cost']:,.2f}</b>
</div>""", unsafe_allow_html=True)

                with d2:
                    st.markdown("**🍽 Food & Beverage**")
                    st.markdown(f"- F&B minimum: **{h['fb_minimum'] or '—'}**")
                    st.markdown(f"- Service charge: {h['fb_service'] or '—'}")
                    st.markdown(f"- F&B tax: {h['fb_tax'] or '—'}")

                with d3:
                    st.markdown("**🏢 Meeting Space**")
                    st.markdown(f"- Total space: **{h['meet_space'] or '—'}**")
                    st.markdown(f"- Meeting cost: {h['meet_cost'] or '—'}")
                    st.markdown("**💰 Commission**")
                    st.markdown(f"- {h['commission'] or '—'}")

# ── Selected summary ──────────────────────────────────────────────────────────
selected_hotels = [h for h in hotels if h['col'] in st.session_state.selected]
st.divider()
st.markdown('<div class="section-title">Selected Hotels</div>', unsafe_allow_html=True)

if not selected_hotels:
    st.warning("No hotels selected yet. Check the boxes next to the hotels you want to include.")
else:
    st.success(f"✅ {len(selected_hotels)} hotel(s) selected")

    rows = []
    for h in selected_hotels:
        rows.append({
            "Hotel":              h["name"],
            "Event Name":         p1_event_name,
            "Client Name":        p1_client_name,
            "Attendees":          p1_attendees,
            "Nights":             p1_nights,
            "Meeting Days":       p1_meeting_days,
            "City":               h["city"],
            "State":              h["state"],
            "Dates":              h["dates"],
            "Availability":       h["availability"],
            "Room Rate":          h["rate_display"] if h["has_rate"] else "Not provided",
            "Room Rate/Room":     h["rate_display_room"] if h["has_rate"] else "Not provided",
            "Rate Single":        h["rate_single"],
            "Rate Double":        h["rate_double"],
            "Rate Basis":            "per person" if h["is_per_person"] else "per room",
            "Tax Included":          "Yes" if h["tax_included"] else "No",
            "Ocean View Rate/Room":  f"{h['ocean_rate_room']:.2f}" if h["ocean_rate_room"] > 0 else "0",
            "Has Room Type Choice":  "Yes" if h["has_room_type_choice"] else "No",
            "Resort Fee":         f"{h['resort_fee']:.2f}" if h["resort_fee"] else "0",
            "Nights":             h["nights"],
            "Est. Accommodation": f"{h['est_cost']:,.2f}" + (f" – {h['est_cost_hi']:,.2f}" if h["is_range"] else ""),
            "F&B Minimum":        h["fb_minimum"],
            "Service Charge":     h["fb_service"],
            "F&B Tax":            h["fb_tax"],
            "Meeting Space":      h["meet_space"],
            "Meeting Cost":       h["meet_cost"],
            "Commission":         h["commission"],
            "Concessions":        h["concessions"],
            # F&B unit costs ($/person) from Cvent
            "FB AM Break $/pp":         h["fb_am_break"],
            "FB PM Break $/pp":         h["fb_pm_break"],
            "FB Continental Bkft $/pp": h["fb_cont_bkft"],
            "FB Buffet Bkft $/pp":      h["fb_buf_bkft"],
            "FB Plated Bkft $/pp":      h["fb_pla_bkft"],
            "FB Buffet Lunch $/pp":     h["fb_buf_lunch"],
            "FB Plated Lunch $/pp":     h["fb_pla_lunch"],
            "FB Buffet Dinner $/pp":    h["fb_buf_din"],
            "FB Plated Dinner $/pp":    h["fb_pla_din"],
            "FB Reception Food $/pp":   h["fb_rec_food"],
            "FB Reception Bev $/pp":    h["fb_rec_bev"],
        })

    # Sort by State, then City
    df_output = pd.DataFrame(rows).sort_values(by=['State', 'City'], na_position='last').reset_index(drop=True)
    
    # Display by state with headers
    for state in df_output['State'].unique():
        st.subheader(f"🏨 {state}")
        state_df = df_output[df_output['State'] == state]
        st.dataframe(state_df, use_container_width=True, hide_index=True)
    
    csv = df_output.to_csv(index=False)

    # Save directly to DocEvents folder
    save_path = os.path.expanduser("~/DocEvents/selected_hotels.csv")
    try:
        with open(save_path, "w") as f:
            f.write(csv)
        st.success(f"✅ Saved to {save_path}")
    except Exception as e:
        st.warning(f"Could not save to DocEvents folder: {e}")

    # Also offer browser download as backup
    st.download_button("⬇️ Download Selected Hotels (CSV)", csv,
                       file_name="selected_hotels.csv", mime="text/csv")
