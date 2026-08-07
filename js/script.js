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

    setUpdatedTime(
        data.updated_at
    );

}


/* ==========================================================
   CLEAR
========================================================== */

function clearDashboard() {

    clearKpis();

    clearTables();

    clearCharts();

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
