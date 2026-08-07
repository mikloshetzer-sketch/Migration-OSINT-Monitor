/*
==========================================================
Migration OSINT Dashboard

File:
js/script.js

Description:
Main application entry point.

Initializes the dashboard, loads data,
renders all UI components and handles refresh.

==========================================================
*/

"use strict";

import {
    getDashboardData
} from "./api.js";

import {
    beginLoading,
    finishLoading,
    loadingFailed,
    setUpdatedTime,
    setRefreshHandler,
    showError,
    showSuccess
} from "./ui.js";

import {
    renderKpis,
    clearKpis
} from "./kpi.js";

import {
    renderSortedTables,
    clearTables
} from "./tables.js";

import {
    renderCharts,
    clearCharts
} from "./charts.js";


/* ==========================================================
   GLOBAL DATA
========================================================== */

let dashboardData = null;


/* ==========================================================
   INITIALIZATION
========================================================== */

document.addEventListener(
    "DOMContentLoaded",
    () => {

        initializeDashboard();

    }
);


/* ==========================================================
   INITIALIZE
========================================================== */

async function initializeDashboard() {

    setRefreshHandler(
        refreshDashboard
    );

    await loadDashboard();

}


/* ==========================================================
   LOAD DASHBOARD
========================================================== */

async function loadDashboard() {

    beginLoading();

    try {

        dashboardData =
            await getDashboardData();

        renderDashboard(
            dashboardData
        );

        finishLoading();

        showSuccess(
            "Dashboard loaded successfully."
        );

    }

    catch (error) {

        console.error(
            error
        );

        loadingFailed();

        clearDashboard();

        showError(
            error.message
        );

    }

}


/* ==========================================================
   REFRESH
========================================================== */

async function refreshDashboard() {

    await loadDashboard();

}


/* ==========================================================
   RENDER
========================================================== */

function renderDashboard(data) {

    if (!data) {
        return;
    }

    renderKpis(
        data
    );

    renderSortedTables(
        data
    );

    renderCharts(
        data
    );

    renderOperationalAssessment(
        data.operational_assessment
    );

    setUpdatedTime(
        data.updated_at
    );

}


/* ==========================================================
   OPERATIONAL ASSESSMENT
========================================================== */

function renderOperationalAssessment(
    assessment
) {

    if (!assessment) {

        clearOperationalAssessment();

        return;

    }

    updateText(
        "assessmentActivity",
        humanizeToken(
            assessment.activity_level
        )
    );

    updateText(
        "assessmentRegion",
        humanizeToken(
            assessment.dominant_region
        )
    );

    updateText(
        "assessmentEventType",
        humanizeToken(
            assessment.dominant_event_type
        )
    );

    updateText(
        "assessmentSource",
        humanizeToken(
            assessment.dominant_source
        )
    );

    updateText(
        "assessmentConfidence",
        formatConfidence(
            assessment.average_confidence
        )
    );

    updateText(
        "assessmentHealth",
        humanizeToken(
            assessment.system_health
        )
    );

    updateText(
        "assessmentSummary",
        assessment.summary
            || "Nincs elérhető automatikus elemzői összefoglaló."
    );

    applyAssessmentStateClass(
        "assessmentActivity",
        assessment.activity_level
    );

    applyAssessmentStateClass(
        "assessmentConfidence",
        assessment.confidence_level
    );

    applyAssessmentStateClass(
        "assessmentHealth",
        assessment.system_health
    );

}


/* ==========================================================
   ASSESSMENT STATE
========================================================== */

function applyAssessmentStateClass(
    elementId,
    value
) {

    const element =
        document.getElementById(
            elementId
        );

    if (!element) {
        return;
    }

    element.classList.remove(
        "assessment-state-low",
        "assessment-state-moderate",
        "assessment-state-elevated",
        "assessment-state-high",
        "assessment-state-normal"
    );

    const normalized =
        String(
            value || ""
        ).toUpperCase();

    if (
        normalized.includes(
            "HIGH"
        )
    ) {

        element.classList.add(
            "assessment-state-high"
        );

        return;

    }

    if (
        normalized.includes(
            "ELEVATED"
        )
    ) {

        element.classList.add(
            "assessment-state-elevated"
        );

        return;

    }

    if (
        normalized.includes(
            "MODERATE"
        )
        ||
        normalized.includes(
            "MEDIUM"
        )
    ) {

        element.classList.add(
            "assessment-state-moderate"
        );

        return;

    }

    if (
        normalized.includes(
            "LOW"
        )
    ) {

        element.classList.add(
            "assessment-state-low"
        );

        return;

    }

    element.classList.add(
        "assessment-state-normal"
    );

}


/* ==========================================================
   ASSESSMENT HELPERS
========================================================== */

function formatConfidence(value) {

    const numericValue =
        Number(
            value
        );

    if (
        Number.isNaN(
            numericValue
        )
    ) {

        return "-";

    }

    return numericValue.toFixed(
        2
    );

}


function humanizeToken(value) {

    if (
        value === null
        ||
        value === undefined
        ||
        value === ""
    ) {

        return "-";

    }

    return String(
        value
    )
        .replaceAll(
            "_",
            " "
        )
        .toLowerCase()
        .replace(
            /\b\w/g,
            letter =>
                letter.toUpperCase()
        );

}


/* ==========================================================
   DOM HELPER
========================================================== */

function updateText(
    elementId,
    value
) {

    const element =
        document.getElementById(
            elementId
        );

    if (!element) {
        return;
    }

    element.textContent =
        value;

}


/* ==========================================================
   CLEAR OPERATIONAL ASSESSMENT
========================================================== */

function clearOperationalAssessment() {

    const ids = [
        "assessmentActivity",
        "assessmentRegion",
        "assessmentEventType",
        "assessmentSource",
        "assessmentConfidence",
        "assessmentHealth"
    ];

    ids.forEach(
        id => {

            const element =
                document.getElementById(
                    id
                );

            if (!element) {
                return;
            }

            element.textContent =
                "-";

            element.classList.remove(
                "assessment-state-low",
                "assessment-state-moderate",
                "assessment-state-elevated",
                "assessment-state-high",
                "assessment-state-normal"
            );

        }
    );

    const summary =
        document.getElementById(
            "assessmentSummary"
        );

    if (summary) {

        summary.textContent =
            "Az automatikus elemzői összefoglaló jelenleg nem érhető el.";

    }

}


/* ==========================================================
   CLEAR
========================================================== */

function clearDashboard() {

    clearKpis();

    clearTables();

    clearCharts();

    clearOperationalAssessment();

}


/* ==========================================================
   AUTO REFRESH
========================================================== */

setInterval(
    async () => {

        try {

            const latest =
                await getDashboardData();

            if (
                latest.updated_at !==
                dashboardData?.updated_at
            ) {

                dashboardData =
                    latest;

                renderDashboard(
                    latest
                );

            }

        }

        catch (error) {

            console.warn(
                error
            );

        }

    },
    60000
);


/* ==========================================================
   DEBUG
========================================================== */

window.dashboard = {

    reload:
        refreshDashboard,

    getData() {

        return dashboardData;

    }

};
