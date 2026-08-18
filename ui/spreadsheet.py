from __future__ import annotations

import base64
import html
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd
import streamlit as st

from utils.city_normalizer import normalize_text
from utils.dates import WEEKDAY_NAMES, business_week

SPREADSHEET_CSS = """
<style>
    :root {
        --jr-navy: #072b58;
        --jr-blue: #12529a;
        --jr-sky: #52a7e8;
        --jr-red: #c81438;
        --jr-red-dark: #99102d;
        --jr-ink: #10243e;
        --jr-muted: #607089;
        --jr-glass: rgba(255, 255, 255, .68);
        --jr-border: rgba(255, 255, 255, .78);
        --jr-shadow: 0 18px 50px rgba(7, 43, 88, .12);
    }
    html {scroll-behavior: smooth;}
    [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(circle at 8% -5%, rgba(82, 167, 232, .24), transparent 30%),
            radial-gradient(circle at 94% 7%, rgba(200, 20, 56, .16), transparent 28%),
            linear-gradient(145deg, #edf4fb 0%, #f9fbfe 48%, #eef3f9 100%);
        background-attachment: fixed;
        overflow-x: hidden;
    }
    [data-testid="stHeader"] {
        background: rgba(244, 248, 253, .62);
        backdrop-filter: blur(18px) saturate(150%);
        border-bottom: 1px solid rgba(255, 255, 255, .65);
    }
    [data-testid="stMainBlockContainer"], .block-container {
        max-width: 1800px;
        padding-top: 1.3rem;
        padding-left: clamp(1rem, 2.5vw, 2.5rem);
        padding-right: clamp(1rem, 2.5vw, 2.5rem);
        padding-bottom: 3rem;
    }
    section[data-testid="stSidebar"] {
        background:
            radial-gradient(circle at 0 0, rgba(82, 167, 232, .30), transparent 32%),
            linear-gradient(165deg, #082f61 0%, #061d3c 62%, #07172d 100%);
        border-right: 1px solid rgba(255, 255, 255, .12);
    }
    section[data-testid="stSidebar"] [data-testid="stLogo"] img {
        border-radius: 20px;
        box-shadow: 0 12px 32px rgba(0, 0, 0, .28);
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] {display: none;}
    .jr-custom-nav a {
        display: flex;
        align-items: center;
        gap: .7rem;
        border: 1px solid transparent;
        border-radius: 14px;
        color: rgba(255, 255, 255, .80);
        margin: 3px 0;
        padding: .7rem .8rem;
        font-size: .9rem;
        font-weight: 650;
        text-decoration: none;
        transition: background .22s ease, border-color .22s ease, transform .22s ease;
    }
    .jr-custom-nav a:hover {
        background: rgba(255, 255, 255, .10);
        border-color: rgba(255, 255, 255, .15);
        color: #fff;
        transform: translateX(3px);
    }
    .jr-custom-nav a.active {
        background: linear-gradient(120deg, rgba(82, 167, 232, .28), rgba(200, 20, 56, .22));
        border-color: rgba(255, 255, 255, .24);
        box-shadow: 0 10px 28px rgba(0, 0, 0, .18);
        color: #fff;
    }
    .jr-nav-icon {display: inline-grid; width: 1.2rem; place-items: center; font-size: 1rem;}
    .jr-nav-label {
        margin: .8rem .4rem .45rem;
        color: rgba(255, 255, 255, .48);
        font-size: .68rem;
        font-weight: 850;
        letter-spacing: .16em;
        text-transform: uppercase;
    }
    .jr-sidebar-signature {
        margin: 1.35rem .4rem 0;
        padding-top: 1rem;
        color: rgba(255, 255, 255, .42);
        font-size: .69rem;
        line-height: 1.5;
        border-top: 1px solid rgba(255, 255, 255, .10);
    }
    h1, h2, h3, h4 {color: var(--jr-ink); letter-spacing: -.025em;}
    p, label {color: #33465f;}
    .jr-hero {
        position: relative;
        display: grid;
        grid-template-columns: auto minmax(0, 1fr) auto;
        align-items: center;
        gap: clamp(1rem, 2vw, 1.6rem);
        min-height: 138px;
        margin: .3rem 0 1.3rem;
        padding: clamp(1.15rem, 2.4vw, 1.8rem);
        overflow: hidden;
        color: #fff;
        background:
            linear-gradient(125deg, rgba(5, 35, 73, .96), rgba(13, 72, 137, .89) 64%, rgba(162, 18, 51, .88));
        border: 1px solid rgba(255, 255, 255, .30);
        border-radius: 28px;
        box-shadow: 0 24px 65px rgba(7, 43, 88, .24), inset 0 1px 0 rgba(255, 255, 255, .20);
        backdrop-filter: blur(24px) saturate(145%);
        animation: jr-rise .55s cubic-bezier(.2, .8, .2, 1) both;
    }
    .jr-hero::before {
        content: "";
        position: absolute;
        width: 330px;
        height: 330px;
        right: -90px;
        top: -205px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(255, 255, 255, .25), rgba(255, 255, 255, 0) 68%);
        animation: jr-float 9s ease-in-out infinite alternate;
        pointer-events: none;
    }
    .jr-hero::after {
        content: "";
        position: absolute;
        inset: 0;
        background: linear-gradient(105deg, transparent 22%, rgba(255, 255, 255, .10) 43%, transparent 61%);
        transform: translateX(-110%);
        animation: jr-shine 8s ease-in-out infinite;
        pointer-events: none;
    }
    .jr-logo-shell {
        position: relative;
        z-index: 1;
        display: grid;
        place-items: center;
        width: 86px;
        height: 86px;
        border-radius: 25px;
        background: rgba(255, 255, 255, .15);
        border: 1px solid rgba(255, 255, 255, .34);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, .26), 0 15px 35px rgba(0, 0, 0, .20);
        backdrop-filter: blur(15px);
    }
    .jr-logo-shell img {width: 68px; height: 68px; border-radius: 16px;}
    .jr-hero-copy {position: relative; z-index: 1;}
    .jr-eyebrow {
        display: inline-flex;
        align-items: center;
        gap: .45rem;
        margin-bottom: .35rem;
        color: rgba(255, 255, 255, .74);
        font-size: .73rem;
        font-weight: 800;
        letter-spacing: .16em;
        text-transform: uppercase;
    }
    .jr-eyebrow::before {content: ""; width: 22px; height: 2px; background: #ff5473; border-radius: 2px;}
    .jr-hero h1 {margin: 0; color: #fff; font-size: clamp(1.65rem, 3.1vw, 2.65rem); line-height: 1.04; letter-spacing: -.045em;}
    .jr-hero p {margin: .55rem 0 0; color: rgba(255, 255, 255, .76); font-size: clamp(.88rem, 1.2vw, 1rem);}
    .jr-status-pill {
        position: relative;
        z-index: 1;
        display: inline-flex;
        align-items: center;
        gap: .55rem;
        padding: .65rem .85rem;
        color: rgba(255, 255, 255, .88);
        font-size: .78rem;
        font-weight: 700;
        white-space: nowrap;
        border: 1px solid rgba(255, 255, 255, .22);
        border-radius: 999px;
        background: rgba(255, 255, 255, .10);
        backdrop-filter: blur(12px);
    }
    .jr-status-dot {width: 8px; height: 8px; border-radius: 50%; background: #79efa8; box-shadow: 0 0 0 5px rgba(121, 239, 168, .13);}
    [data-testid="stForm"], [data-testid="stMetric"], [data-testid="stExpander"] details,
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--jr-glass);
        border: 1px solid var(--jr-border) !important;
        border-radius: 20px !important;
        box-shadow: var(--jr-shadow);
        backdrop-filter: blur(20px) saturate(150%);
    }
    [data-testid="stForm"] {padding: 1rem 1.15rem;}
    [data-testid="stMetric"] {padding: 1rem 1.1rem; overflow: hidden; position: relative;}
    [data-testid="stMetric"]::before {
        content: "";
        position: absolute;
        width: 4px;
        inset: 12px auto 12px 0;
        border-radius: 0 5px 5px 0;
        background: linear-gradient(var(--jr-blue), var(--jr-red));
    }
    [data-testid="stMetricValue"] {color: var(--jr-navy); font-weight: 800;}
    [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
    [data-testid="stDateInput"] input, [data-baseweb="select"] > div,
    [data-testid="stFileUploaderDropzone"] {
        background: rgba(255, 255, 255, .70) !important;
        border-color: rgba(18, 82, 154, .15) !important;
        border-radius: 14px !important;
        transition: border-color .2s ease, box-shadow .2s ease, background .2s ease;
    }
    [data-testid="stTextInput"] input:focus, [data-testid="stNumberInput"] input:focus,
    [data-testid="stDateInput"] input:focus {
        border-color: rgba(18, 82, 154, .58) !important;
        box-shadow: 0 0 0 4px rgba(18, 82, 154, .10) !important;
        background: #fff !important;
    }
    .stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
        position: relative;
        overflow: hidden;
        min-height: 2.65rem;
        color: var(--jr-navy);
        font-weight: 750;
        border: 1px solid rgba(18, 82, 154, .18);
        border-radius: 14px;
        background: rgba(255, 255, 255, .70);
        box-shadow: 0 8px 22px rgba(7, 43, 88, .08), inset 0 1px 0 rgba(255, 255, 255, .85);
        backdrop-filter: blur(14px);
        transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover, [data-testid="stFormSubmitButton"] > button:hover {
        color: var(--jr-blue);
        border-color: rgba(18, 82, 154, .40);
        box-shadow: 0 12px 28px rgba(7, 43, 88, .14), inset 0 1px 0 #fff;
        transform: translateY(-2px);
    }
    .stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primary"] {
        color: #fff;
        border-color: rgba(255, 255, 255, .22);
        background: linear-gradient(120deg, var(--jr-blue), var(--jr-navy) 58%, #7f173e);
        box-shadow: 0 12px 28px rgba(7, 43, 88, .24), inset 0 1px 0 rgba(255, 255, 255, .22);
    }
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        gap: .45rem;
        padding: .35rem;
        border-radius: 16px;
        background: rgba(255, 255, 255, .54);
        border: 1px solid rgba(255, 255, 255, .75);
        backdrop-filter: blur(16px);
    }
    [data-testid="stTabs"] [data-baseweb="tab"] {border-radius: 12px; padding: .65rem 1rem;}
    [data-testid="stTabs"] [aria-selected="true"] {background: rgba(18, 82, 154, .11); color: var(--jr-blue);}
    [data-testid="stDataFrame"], [data-testid="stDataEditor"] {
        overflow: hidden;
        border: 1px solid rgba(255, 255, 255, .84);
        border-radius: 20px;
        box-shadow: var(--jr-shadow);
    }
    [data-testid="stAlert"] {
        border-radius: 16px;
        border: 1px solid rgba(255, 255, 255, .72);
        box-shadow: 0 10px 30px rgba(7, 43, 88, .08);
        backdrop-filter: blur(14px);
    }
    .st-key-week_navigation {max-width: 42rem;}
    .st-key-schedule_actions {max-width: 36rem; margin-top: .75rem;}
    .route-sheet-shell {
        padding: 1rem;
        border: 1px solid rgba(255, 255, 255, .84);
        border-radius: 24px;
        background: rgba(255, 255, 255, .58);
        box-shadow: var(--jr-shadow);
        backdrop-filter: blur(22px) saturate(150%);
        animation: jr-rise .5s .08s cubic-bezier(.2, .8, .2, 1) both;
    }
    .route-week-mobile {display: none;}
    .route-sheet-scroll {overflow-x: auto; border-radius: 17px;}
    .route-sheet {border-collapse: separate; border-spacing: 0; table-layout: fixed; min-width: 920px; width: 100%; background: rgba(255,255,255,.50); font-family: Inter, "Segoe UI", sans-serif; font-size: 13px;}
    .route-sheet th, .route-sheet td {border-right: 1px solid rgba(7,43,88,.10); border-bottom: 1px solid rgba(7,43,88,.10); padding: 8px 10px; text-align: left; vertical-align: middle; overflow-wrap: anywhere;}
    .route-sheet th {background: linear-gradient(145deg, #0c477f, #082f61); text-align: center; color: #fff; font-weight: 780; border-color: rgba(255,255,255,.13);}
    .route-sheet th:first-child {border-radius: 16px 0 0 0;}
    .route-sheet th:last-child {border-radius: 0 16px 0 0; border-right: 0;}
    .route-sheet th.alert {background: linear-gradient(145deg, #d22147, #9b1131); color: #fff;}
    .route-sheet td {height: 36px; background: rgba(255,255,255,.74); transition: background .18s ease;}
    .route-sheet tr:hover td {background: rgba(235, 245, 255, .91);}
    .route-sheet td.alert {background: linear-gradient(115deg, rgba(255,220,227,.96), rgba(255,239,242,.92)); color: #a30f30; font-weight: 760; cursor: pointer; padding: 0;}
    .route-sheet details.holiday-cell summary {display: flex; align-items: center; justify-content: space-between; gap: 8px; color: inherit; padding: 7px 9px; list-style: none;}
    .route-sheet details.holiday-cell summary::-webkit-details-marker {display: none;}
    .route-sheet details.holiday-cell summary::after {content: "+"; flex: 0 0 auto; font-size: 16px; font-weight: 850; line-height: 1;}
    .route-sheet details.holiday-cell[open] summary::after {content: "−";}
    .route-sheet details.holiday-cell summary:hover {background: rgba(200, 20, 56, .08);}
    .route-sheet details.holiday-cell[open] summary {background: rgba(200, 20, 56, .10);}
    .route-sheet .holiday-inline-details {background: rgba(255,255,255,.78); border-top: 1px solid rgba(200,20,56,.25); color: #26394f; font-weight: 400; padding: 9px 10px; line-height: 1.5; animation: jr-detail .22s ease-out both;}
    .route-sheet .holiday-inline-details strong {color: #a30f30;}
    .route-sheet .holiday-inline-item + .holiday-inline-item {border-top: 1px solid rgba(200,20,56,.16); margin-top: 7px; padding-top: 7px;}
    .route-sheet td.empty {color: #aaa;}
    .sheet-caption {color: var(--jr-muted); font-size: 13px; margin: 0 0 .75rem;}
    .mobile-table-hint {display: none;}
    .holiday-mobile-list {display: none;}
    .route-info-grid {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: .75rem;
        align-items: start;
    }
    .route-info-card {
        overflow: hidden;
        border: 1px solid rgba(255,255,255,.84);
        border-radius: 18px;
        background: rgba(255,255,255,.64);
        box-shadow: 0 14px 34px rgba(7,43,88,.10);
        backdrop-filter: blur(18px) saturate(145%);
    }
    .route-info-card.is-empty {opacity: .68;}
    .route-info-header {
        min-height: 92px;
        padding: .8rem;
        color: #fff;
        background: linear-gradient(145deg, #0c477f, #082f61);
    }
    .route-info-day {font-size: .7rem; font-weight: 820; letter-spacing: .07em; text-transform: uppercase; opacity: .78;}
    .route-info-name {margin-top: .28rem; font-size: .82rem; font-weight: 790; line-height: 1.25;}
    .route-info-count {margin-top: .3rem; font-size: .68rem; opacity: .72;}
    .route-info-cities {margin: 0; padding: 0; list-style: none;}
    .route-info-city {padding: .62rem .7rem; color: var(--jr-ink); font-size: .76rem; line-height: 1.3; border-top: 1px solid rgba(7,43,88,.08);}
    .route-info-city:first-child {border-top: 0;}
    .route-info-official {display: block; margin-top: .16rem; color: var(--jr-muted); font-size: .65rem;}
    .route-info-empty {padding: 1rem .7rem; color: var(--jr-muted); font-size: .74rem; text-align: center;}
    @keyframes jr-rise {from {opacity: 0; transform: translateY(12px) scale(.992);} to {opacity: 1; transform: translateY(0) scale(1);}}
    @keyframes jr-detail {from {opacity: 0; transform: translateY(-4px);} to {opacity: 1; transform: translateY(0);}}
    @keyframes jr-float {from {transform: translate3d(0,0,0) scale(1);} to {transform: translate3d(-25px,28px,0) scale(1.08);}}
    @keyframes jr-shine {0%, 72% {transform: translateX(-110%);} 88%, 100% {transform: translateX(110%);}}
    @media (max-width: 780px) {
        [data-testid="stMainBlockContainer"], .block-container {
            padding: .65rem .65rem 2rem;
        }
        [data-testid="stHeader"] {height: 3.25rem;}
        [data-testid="stSidebarCollapsedControl"] button,
        [data-testid="stSidebarCollapseButton"] button {min-width: 44px; min-height: 44px;}
        section[data-testid="stSidebar"] {width: min(86vw, 320px) !important;}
        .jr-hero {
            grid-template-columns: auto minmax(0, 1fr);
            min-height: 0;
            gap: .75rem;
            margin: 0 0 .9rem;
            padding: .85rem;
            border-radius: 19px;
        }
        .jr-logo-shell {width: 54px; height: 54px; border-radius: 16px;}
        .jr-logo-shell img {width: 44px; height: 44px; border-radius: 11px;}
        .jr-eyebrow {margin-bottom: .2rem; font-size: .58rem; letter-spacing: .11em;}
        .jr-eyebrow::before {width: 13px;}
        .jr-hero h1 {font-size: clamp(1.22rem, 6vw, 1.58rem); line-height: 1.08;}
        .jr-hero p {margin-top: .3rem; font-size: .78rem; line-height: 1.35;}
        .jr-status-pill {display: none;}
        h1 {font-size: 1.65rem;}
        h2 {font-size: 1.4rem;}
        h3 {font-size: 1.18rem;}
        [data-testid="stForm"] {padding: .8rem; border-radius: 16px !important;}
        [data-testid="stForm"] [data-testid="stHorizontalBlock"] {
            flex-direction: column;
            gap: .35rem;
        }
        [data-testid="stForm"] [data-testid="stColumn"] {
            width: 100% !important;
            flex: 1 1 auto !important;
        }
        [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {
            flex-wrap: wrap;
            gap: .55rem;
        }
        [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"] {
            min-width: calc(50% - .3rem) !important;
            flex: 1 1 calc(50% - .3rem) !important;
        }
        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input,
        [data-testid="stDateInput"] input,
        [data-baseweb="select"] input {font-size: 16px !important;}
        .stButton > button, .stDownloadButton > button,
        [data-testid="stFormSubmitButton"] > button {
            min-height: 44px;
            padding-left: .65rem;
            padding-right: .65rem;
        }
        [data-testid="stTabs"] [data-baseweb="tab-list"] {
            overflow-x: auto;
            scrollbar-width: none;
        }
        [data-testid="stTabs"] [data-baseweb="tab-list"]::-webkit-scrollbar {display: none;}
        [data-testid="stTabs"] [data-baseweb="tab"] {min-width: max-content; min-height: 44px;}
        [data-testid="stDataFrame"], [data-testid="stDataEditor"] {
            width: 100%;
            max-width: calc(100vw - 1.3rem);
            overflow: auto !important;
            border-radius: 14px;
            -webkit-overflow-scrolling: touch;
            touch-action: pan-x pan-y;
        }
        [data-testid="stAlert"] {border-radius: 13px;}
        .route-sheet-shell {padding: .55rem; border-radius: 17px;}
        .route-sheet-desktop {display: none;}
        .route-week-mobile {display: grid; gap: .7rem;}
        .route-day-card {
            overflow: hidden;
            border: 1px solid rgba(7,43,88,.10);
            border-radius: 15px;
            background: rgba(255,255,255,.72);
            box-shadow: 0 8px 22px rgba(7,43,88,.08);
        }
        .route-day-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: .7rem;
            padding: .75rem .8rem;
            color: #fff;
            background: linear-gradient(145deg, #0c477f, #082f61);
        }
        .route-day-card.alert .route-day-header {background: linear-gradient(145deg, #d22147, #9b1131);}
        .route-day-name {display: block; font-size: .75rem; font-weight: 820; text-transform: uppercase; letter-spacing: .045em;}
        .route-day-date {display: block; margin-top: .08rem; font-size: .72rem; opacity: .78;}
        .route-day-count {
            flex: 0 0 auto;
            padding: .28rem .5rem;
            border: 1px solid rgba(255,255,255,.22);
            border-radius: 999px;
            background: rgba(255,255,255,.12);
            font-size: .68rem;
            font-weight: 720;
        }
        .route-mobile-item {
            min-height: 44px;
            padding: .72rem .8rem;
            color: var(--jr-ink);
            font-size: .82rem;
            border-top: 1px solid rgba(7,43,88,.08);
        }
        .route-mobile-item:first-child {border-top: 0;}
        details.route-mobile-item {padding: 0; color: #a30f30; background: rgba(255,226,232,.78); font-weight: 760;}
        details.route-mobile-item summary {
            display: flex;
            align-items: center;
            justify-content: space-between;
            min-height: 44px;
            padding: .72rem .8rem;
            list-style: none;
        }
        details.route-mobile-item summary::-webkit-details-marker {display: none;}
        details.route-mobile-item summary::after {content: "+"; font-size: 1.05rem;}
        details.route-mobile-item[open] summary::after {content: "−";}
        details.route-mobile-item .holiday-inline-details {
            padding: .7rem .8rem;
            color: #26394f;
            font-size: .77rem;
            font-weight: 400;
            line-height: 1.55;
            border-top: 1px solid rgba(200,20,56,.22);
            background: rgba(255,255,255,.72);
            animation: jr-detail .22s ease-out both;
        }
        details.route-mobile-item .holiday-inline-details strong {color: #a30f30;}
        details.route-mobile-item .holiday-inline-item + .holiday-inline-item {
            margin-top: .55rem;
            padding-top: .55rem;
            border-top: 1px solid rgba(200,20,56,.14);
        }
        .route-mobile-empty {padding: .8rem; color: var(--jr-muted); font-size: .8rem; text-align: center;}
        .holiday-mobile-list {display: grid; gap: .65rem;}
        .holiday-mobile-card {
            padding: .85rem;
            border: 1px solid rgba(255,255,255,.84);
            border-radius: 16px;
            background: rgba(255,255,255,.68);
            box-shadow: 0 10px 26px rgba(7,43,88,.09);
            backdrop-filter: blur(16px);
        }
        .holiday-mobile-date {color: var(--jr-red-dark); font-size: .75rem; font-weight: 820; text-transform: uppercase;}
        .holiday-mobile-name {margin: .2rem 0 .55rem; color: var(--jr-ink); font-size: .98rem; font-weight: 780;}
        .holiday-mobile-meta {display: grid; grid-template-columns: 1fr auto; gap: .35rem .7rem; color: var(--jr-muted); font-size: .77rem;}
        .route-info-grid {grid-template-columns: 1fr; gap: .7rem;}
        .route-info-header {min-height: 0; padding: .75rem .8rem;}
        .route-info-name {font-size: .88rem;}
        .route-info-city {min-height: 42px; padding: .7rem .8rem; font-size: .8rem;}
        .mobile-table-hint {display: block; margin: .25rem 0 .5rem; color: var(--jr-muted); font-size: .75rem;}
        .st-key-holiday_table {display: none;}
        .st-key-week_navigation [data-testid="stHorizontalBlock"] {gap: .35rem; flex-wrap: nowrap;}
        .st-key-week_navigation [data-testid="stColumn"] {min-width: 0 !important; flex: 1 1 0 !important;}
        .st-key-week_navigation button {font-size: .72rem; line-height: 1.15;}
        .st-key-schedule_actions [data-testid="stHorizontalBlock"] {gap: .5rem;}
    }
    @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after {animation-duration: .01ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; transition-duration: .01ms !important;}
    }
</style>
"""

LOGO_PATH = Path(__file__).resolve().parents[1] / "static" / "logo-jr.png"


@lru_cache(maxsize=1)
def _logo_data_uri() -> str:
    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def apply_spreadsheet_style(active_page: str = "schedule") -> None:
    if LOGO_PATH.exists():
        st.logo(str(LOGO_PATH), size="large", icon_image=str(LOGO_PATH))
    st.markdown(SPREADSHEET_CSS, unsafe_allow_html=True)
    links = (
        ("schedule", "./", "▦", "Escala semanal"),
        ("route_info", "./Informacoes_de_Rotas", "☷", "Informações das rotas"),
        ("routes", "./Cadastro_de_Rotas", "⇆", "Cadastro de rotas"),
        ("holidays", "./Feriados", "◈", "Feriados"),
        ("settings", "./Configuracoes", "⚙", "Configurações"),
    )
    nav_links = "".join(
        f'<a class="{"active" if key == active_page else ""}" href="{href}" target="_self">'
        f'<span class="jr-nav-icon">{icon}</span>{label}</a>'
        for key, href, icon, label in links
    )
    with st.sidebar:
        st.markdown(
            '<div class="jr-nav-label">Operação</div>'
            f'<nav class="jr-custom-nav">{nav_links}</nav>'
            '<div class="jr-sidebar-signature">JR Ferragens &amp; Madeiras<br>'
            "Inteligência para transportes</div>",
            unsafe_allow_html=True,
        )


def render_page_header(
    title: str,
    subtitle: str,
    eyebrow: str = "JR Ferragens & Madeiras",
) -> None:
    logo = _logo_data_uri() if LOGO_PATH.exists() else ""
    logo_html = (
        f'<div class="jr-logo-shell"><img src="{logo}" alt="Logo JR"></div>'
        if logo
        else ""
    )
    st.markdown(
        '<section class="jr-hero">'
        f"{logo_html}"
        '<div class="jr-hero-copy">'
        f'<div class="jr-eyebrow">{html.escape(eyebrow)}</div>'
        f"<h1>{html.escape(title)}</h1>"
        f"<p>{html.escape(subtitle)}</p>"
        "</div>"
        '<div class="jr-status-pill"><span class="jr-status-dot"></span>Sistema operacional</div>'
        "</section>",
        unsafe_allow_html=True,
    )


def render_schedule_table(
    monday: date, schedule: dict[date, list], matches: list
) -> None:
    days = business_week(monday)
    match_map: dict[tuple[date, int], list] = {}
    for match in matches:
        match_map.setdefault((match.date, match.route_id), []).append(match)
    max_rows = max((len(schedule.get(day, [])) for day in days), default=0)
    max_rows = max(max_rows, 1)
    desktop_parts = [
        (
            '<div class="route-sheet-shell">'
            '<div class="sheet-caption">Selecione um item vermelho para abrir os detalhes do feriado.</div>'
            '<div class="route-sheet-desktop"><div class="route-sheet-scroll">'
        )
    ]
    desktop_parts.append('<table class="route-sheet"><thead><tr>')
    for index, day in enumerate(days):
        alert = any(match.date == day for match in matches)
        class_name = ' class="alert"' if alert else ""
        prefix = "🔴 " if alert else ""
        desktop_parts.append(
            f"<th{class_name}>{prefix}{html.escape(WEEKDAY_NAMES[index])}<br>{day:%d/%m/%Y}</th>"
        )
    desktop_parts.append("</tr></thead><tbody>")
    for row_index in range(max_rows):
        desktop_parts.append("<tr>")
        for day in days:
            routes = schedule.get(day, [])
            if row_index >= len(routes):
                desktop_parts.append('<td class="empty">&nbsp;</td>')
                continue
            route = routes[row_index]
            affected = match_map.get((day, route.id), [])
            if affected:
                tooltip = " | ".join(
                    f"{item.city} — {item.name} ({item.holiday_type})"
                    for item in affected
                )
                details = "".join(
                    '<div class="holiday-inline-item">'
                    f"<div><strong>Cidade:</strong> {html.escape(item.city)}</div>"
                    f"<div><strong>Feriado:</strong> {html.escape(item.name)}</div>"
                    f"<div><strong>Tipo:</strong> {html.escape(item.holiday_type)}</div>"
                    "</div>"
                    for item in affected
                )
                desktop_parts.append(
                    f'<td class="alert" title="{html.escape(tooltip, quote=True)}">'
                    '<details class="holiday-cell">'
                    f"<summary>⚠ {html.escape(route.label)}</summary>"
                    f'<div class="holiday-inline-details">{details}</div>'
                    "</details>"
                    "</td>"
                )
            else:
                desktop_parts.append(f"<td>{html.escape(route.label)}</td>")
        desktop_parts.append("</tr>")
    desktop_parts.append("</tbody></table></div></div>")

    mobile_parts = ['<div class="route-week-mobile">']
    for index, day in enumerate(days):
        routes = schedule.get(day, [])
        day_has_alert = any(match.date == day for match in matches)
        alert_class = " alert" if day_has_alert else ""
        route_word = "rota" if len(routes) == 1 else "rotas"
        mobile_parts.append(
            f'<section class="route-day-card{alert_class}">'
            '<header class="route-day-header"><div>'
            f'<span class="route-day-name">{html.escape(WEEKDAY_NAMES[index])}</span>'
            f'<span class="route-day-date">{day:%d/%m/%Y}</span>'
            "</div>"
            f'<span class="route-day-count">{len(routes)} {route_word}</span>'
            "</header>"
        )
        if not routes:
            mobile_parts.append(
                '<div class="route-mobile-empty">Nenhuma rota programada</div>'
            )
        for route in routes:
            affected = match_map.get((day, route.id), [])
            if not affected:
                mobile_parts.append(
                    f'<div class="route-mobile-item">{html.escape(route.label)}</div>'
                )
                continue
            details = "".join(
                '<div class="holiday-inline-item">'
                f"<div><strong>Cidade:</strong> {html.escape(item.city)}</div>"
                f"<div><strong>Feriado:</strong> {html.escape(item.name)}</div>"
                f"<div><strong>Tipo:</strong> {html.escape(item.holiday_type)}</div>"
                "</div>"
                for item in affected
            )
            mobile_parts.append(
                '<details class="route-mobile-item">'
                f"<summary>⚠ {html.escape(route.label)}</summary>"
                f'<div class="holiday-inline-details">{details}</div>'
                "</details>"
            )
        mobile_parts.append("</section>")
    mobile_parts.append("</div></div>")
    st.markdown("".join([*desktop_parts, *mobile_parts]), unsafe_allow_html=True)


def render_holiday_cards(entries: list) -> None:
    parts = ['<div class="holiday-mobile-list">']
    for item in entries:
        parts.append(
            '<article class="holiday-mobile-card">'
            f'<div class="holiday-mobile-date">{item.date:%d/%m/%Y} • {html.escape(item.holiday_type)}</div>'
            f'<div class="holiday-mobile-name">{html.escape(item.holiday_name)}</div>'
            '<div class="holiday-mobile-meta">'
            f'<span>{html.escape(item.city)} / {html.escape(item.state)}</span>'
            f'<span>{html.escape(item.source)}</span>'
            "</div>"
            "</article>"
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_route_weekday_profiles(route, profiles: list) -> None:
    profile_by_weekday = {profile.weekday: profile for profile in profiles}
    parts = ['<div class="route-info-grid">']
    for weekday, weekday_name in enumerate(WEEKDAY_NAMES):
        profile = profile_by_weekday.get(weekday)
        if profile is None:
            parts.append(
                '<section class="route-info-card is-empty">'
                '<header class="route-info-header">'
                f'<div class="route-info-day">{html.escape(weekday_name)}</div>'
                f'<div class="route-info-name">{html.escape(route.label)}</div>'
                "</header>"
                '<div class="route-info-empty">Rota não programada neste dia</div>'
                "</section>"
            )
            continue
        city_word = "cidade" if len(profile.cities) == 1 else "cidades"
        parts.append(
            '<section class="route-info-card">'
            '<header class="route-info-header">'
            f'<div class="route-info-day">{html.escape(weekday_name)}</div>'
            f'<div class="route-info-name">{html.escape(profile.label)}</div>'
            f'<div class="route-info-count">{len(profile.cities)} {city_word}</div>'
            "</header>"
        )
        if not profile.cities:
            parts.append(
                '<div class="route-info-empty">Nenhuma cidade informada na planilha</div>'
            )
        else:
            parts.append('<ul class="route-info-cities">')
            for city in profile.cities:
                official = ""
                if city.municipality_name and normalize_text(
                    city.municipality_name
                ) != normalize_text(city.city_original):
                    official = (
                        '<span class="route-info-official">Município: '
                        f"{html.escape(city.municipality_name)} / {html.escape(city.state)}"
                        "</span>"
                    )
                parts.append(
                    '<li class="route-info-city">'
                    f"{html.escape(city.city_original)}{official}</li>"
                )
            parts.append("</ul>")
        parts.append("</section>")
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def schedule_dataframe(monday: date, schedule: dict[date, list]) -> pd.DataFrame:
    days = business_week(monday)
    max_rows = max((len(schedule.get(day, [])) for day in days), default=0)
    max_rows = max(max_rows + 1, 2)
    data = {}
    for index, day in enumerate(days):
        values = [route.label for route in schedule.get(day, [])]
        values.extend([""] * (max_rows - len(values)))
        data[f"{WEEKDAY_NAMES[index]} {day:%d/%m}"] = values
    return pd.DataFrame(data)
