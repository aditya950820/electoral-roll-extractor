"""Shared Streamlit pieces for the review pages: flag cards, the grouped
house_overload view with family-tree reconstruction, and infinite scroll."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from family import analyse_household, cluster_dot
from fraud_rules import (all_flags_for_export, get_photo,
                         house_overload_members_for_export, house_members)

# ---------------------------------------------------------------- infinite scroll
PAGE_STEP = 100

_autoload = components.declare_component(
    "autoload", path=str(Path(__file__).parent / "components" / "autoload"))


def infinite_limit(state_key: str) -> int:
    """How many rows to fetch right now for this list."""
    return PAGE_STEP * (1 + st.session_state.get(state_key, 0))


def infinite_scroll_sentinel(state_key: str, has_more: bool) -> None:
    """Place at the very bottom of the list. Scrolling it into view bumps the
    page counter and reruns, which loads PAGE_STEP more rows."""
    fire = _autoload(has_more=has_more, key=f"sentinel::{state_key}", default=0)
    if has_more:
        st.caption("Loading more as you scroll…")
        # The component sends a fresh timestamp each time the sentinel is
        # visible; any value we haven't seen yet means "load another page".
        seen_key = f"{state_key}::seen"
        if fire and fire != st.session_state.get(seen_key):
            st.session_state[seen_key] = fire
            st.session_state[state_key] = st.session_state.get(state_key, 0) + 1
            st.rerun()
    else:
        st.caption("— end of list —")


# ---------------------------------------------------------------- flag cards
def flag_title(f) -> str:
    sev_icon = {"high": "🔴", "medium": "🟠"}.get(f["severity"], "🟡")
    d = f.get("details") or {}
    if f["rule"] == "house_overload" and d.get("house_norm"):
        return (f"{sev_icon} **house_overload** — House {d.get('house') or '?'} "
                f"(AC {d.get('constituency_no') or '?'}) — "
                f"{d.get('occupants', '?')} electors")
    return (f"{sev_icon} **{f['rule']}** — {f['name_a']} "
            f"({f['epic_a'] or 'no EPIC'})"
            + (f"  ↔  {f['name_b']} ({f['epic_b'] or 'no EPIC'})"
               if f["name_b"] else ""))


def _voter_md(f, side: str) -> str:
    return (f"**{f['name_' + side]}**  \n"
            f"EPIC: `{f['epic_' + side]}`  \n"
            f"AC {f['const_' + side] or '?'} · Part {f['part_' + side]} · "
            f"Serial {f['serial_' + side] if f['serial_' + side] is not None else '?'}  \n"
            f"House {f['house_' + side]}  \n"
            f"Age {f['age_' + side]} · {f['gender_' + side]}")


def flag_card(f) -> None:
    """Body of one flag expander: pair of voter cards, or — for a grouped
    house_overload flag — every occupant plus the reconstructed family tree."""
    d = f.get("details") or {}
    if f["rule"] == "house_overload" and d.get("house_norm"):
        _house_overload_card(f, d)
        return

    cols = st.columns([2, 1, 2, 1]) if f["name_b"] else st.columns([2, 1])
    cols[0].markdown(_voter_md(f, "a"))
    pa = get_photo(f["voter_id"])
    if pa:
        cols[1].image(pa, width=110)
    if f["name_b"]:
        cols[2].markdown(_voter_md(f, "b"))
        pb = get_photo(f["related_voter_id"])
        if pb:
            cols[3].image(pb, width=110)
    st.json(f["details"], expanded=False)


def _house_overload_card(f, d: dict) -> None:
    members = house_members(d.get("constituency_no"), d["house_norm"])
    if not members:
        st.warning("No electors found for this house any more (data re-ingested?).")
        st.json(d, expanded=False)
        return

    hh = analyse_household(members)
    by_id = {m["id"]: m for m in hh.members}

    st.markdown(f"### 🏠 House `{d.get('house') or f['house_a']}` — "
                f"AC {d.get('constituency_no') or '?'} — "
                f"**{len(members)} electors** at this address")
    for line in hh.signals:
        st.markdown(f"- {line}")

    # ---- reconstructed family groups (tree per group)
    fams = [c for c in hh.clusters if len(c) >= 2]
    if fams:
        st.markdown("**Family groups** (arrows: parent → child, "
                    "purple line: spouses, red: anomaly):")
        for i, cluster in enumerate(fams, 1):
            with st.expander(f"Family group {i} — {len(cluster)} members",
                             expanded=len(fams) <= 3):
                st.graphviz_chart(cluster_dot(hh, cluster))

    # ---- the prime suspects: nobody in the house is family to them
    if hh.unlinked:
        st.markdown("**⚠️ Unattached electors** — no family link to anyone "
                    "here (verify these first):")
        st.dataframe(_members_df([by_id[v] for v in hh.unlinked], hh),
                     use_container_width=True, hide_index=True)

    # ---- everyone, grouped, in one table
    with st.expander(f"All {len(members)} electors in this house", expanded=False):
        group_of = {vid: i for i, c in enumerate(hh.clusters, 1)
                    for vid in c if len(c) >= 2}
        df = _members_df(hh.members, hh)
        df.insert(0, "Family", [group_of.get(m["id"], "—") for m in hh.members])
        st.dataframe(df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------- export
_SIDE_A_COLS = {
    "name_a": "Name (A)", "epic_a": "EPIC (A)", "relation_type_a": "Relation Type (A)",
    "relation_name_a": "Relation Name (A)", "const_a": "AC No. (A)", "part_a": "Part (A)",
    "serial_a": "Serial (A)", "house_a": "House (A)", "age_a": "Age (A)", "gender_a": "Gender (A)",
}
_SIDE_B_COLS = {
    "name_b": "Name (B)", "epic_b": "EPIC (B)", "relation_type_b": "Relation Type (B)",
    "relation_name_b": "Relation Name (B)", "const_b": "AC No. (B)", "part_b": "Part (B)",
    "serial_b": "Serial (B)", "house_b": "House (B)", "age_b": "Age (B)", "gender_b": "Gender (B)",
}


def build_flags_export(rule_filter: str | None) -> bytes:
    """Excel workbook: every flag with both voters' details side-by-side (the
    same fields the review card shows), plus a sheet listing every occupant
    of each flagged house_overload house."""
    rows = all_flags_for_export(rule_filter)
    front = ["id", "rule", "severity", "score", "verdict", "reviewer", "notes",
             "reviewed_at"]
    records = []
    for f in rows:
        rec = {k: f.get(k) for k in front}
        for k, label in _SIDE_A_COLS.items():
            rec[label] = f.get(k)
        for k, label in _SIDE_B_COLS.items():
            rec[label] = f.get(k)
        rec["Details"] = f.get("details")
        records.append(rec)
    flags_df = pd.DataFrame(records)

    house_rows = house_overload_members_for_export(rule_filter)
    house_df = pd.DataFrame(house_rows) if house_rows else pd.DataFrame(
        columns=["flag_id", "house", "constituency_no", "id", "name",
                "relation_type", "relation_name", "age", "gender", "serial_no",
                "part_no", "house_number", "epic_no", "constituency_no"])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        flags_df.to_excel(xl, index=False, sheet_name="Flags")
        house_df.to_excel(xl, index=False, sheet_name="House Overload Members")
    return buf.getvalue()


def _members_df(members: list, hh) -> "pd.DataFrame":
    return pd.DataFrame([{
        "Serial": m.get("serial_no"),
        "Part": m.get("part_no"),
        "Name": m.get("name"),
        "Age": m.get("age"),
        "G": m.get("gender"),
        "Relation": f"{m.get('relation_type') or ''} {m.get('relation_name') or ''}".strip(),
        "EPIC": m.get("epic_no"),
        "Notes": "; ".join(hh.anomalies.get(m["id"], [])),
    } for m in members])
