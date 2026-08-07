/*
==========================================================
Migration OSINT Dashboard

File:
js/charts.js

Description:
Renders analytical dashboard visualizations:

- Region Activity
- Source Activity
- Processing Funnel metrics

Dependencies:
utils.js
Chart.js

==========================================================
*/

"use strict";

import {
    formatNumber,
    formatPercent,
    escapeHtml
} from "./utils.js";


/* ==========================================================
   CHART REFERENCES
========================================================== */

let regionChartInstance = null;
let sourceChartInstance = null;


/* ==========================================================
   COLORS
========================================================== */

const REGION_COLORS = [
    "#168fc7",
    "#20a96b",
    "#e58a00",
    "#7a57d1",
    "#cf473b",
    "#6e8ea0",
    "#3fb8b0",
    "#b78e29"
];


const SOURCE_COLORS = [
    "#168fc7",
    "#e58a00",
    "#20a96b",
    "#7a57d1",
    "#cf473b",
    "#6e8ea0",
    "#3fb8b0",
    "#b78e29"
];


/* ==========================================================
   PUBLIC API
========================================================== */

export function renderCharts(data) {

    renderRegionActivity(
        data?.region_activity || []
    );

    renderSourceActivity(
        data?.source_activity || []
    );

    renderCorrelationMetrics(
        data?.correlation || {}
    );

}


/* ==========================================================
   REGION ACTIVITY
========================================================== */

export function renderRegionActivity(regionActivity) {

    renderRegionChart(
        regionActivity
    );

    renderRegionList(
        regionActivity
    );

}


function renderRegionChart(regionActivity) {

    const canvas =
        document.getElementById(
            "regionChart"
        );

    if (!canvas) {
        return;
    }

    if (regionChartInstance) {

        regionChartInstance.destroy();

        regionChartInstance = null;

    }

    if (
        !Array.isArray(regionActivity) ||
        regionActivity.length === 0
    ) {

        return;
    }

    const labels =
        regionActivity.map(
            item =>
                humanizeToken(
                    item?.region || "GLOBAL"
                )
        );

    const values =
        regionActivity.map(
            item =>
                Number(
                    item?.count || 0
                )
        );

    const total =
        values.reduce(
            (
                sum,
                value
            ) => sum + value,
            0
        );

    regionChartInstance =
        new Chart(
            canvas,
            {
                type: "doughnut",

                data: {
                    labels,

                    datasets: [
                        {
                            data:
                                values,

                            backgroundColor:
                                buildColorArray(
                                    REGION_COLORS,
                                    values.length
                                ),

                            borderColor:
                                "#ffffff",

                            borderWidth:
                                2,

                            hoverOffset:
                                5
                        }
                    ]
                },

                options: {

                    responsive:
                        true,

                    maintainAspectRatio:
                        false,

                    cutout:
                        "64%",

                    animation: {
                        duration:
                            650
                    },

                    plugins: {

                        legend: {
                            display:
                                false
                        },

                        tooltip: {

                            callbacks: {

                                label(
                                    context
                                ) {

                                    const value =
                                        Number(
                                            context.raw || 0
                                        );

                                    const percent =
                                        calculatePercent(
                                            value,
                                            total
                                        );

                                    return (
                                        `${context.label}: `
                                        + `${formatNumber(value)} `
                                        + `(${percent.toFixed(1)}%)`
                                    );

                                }

                            }

                        }

                    }

                }
            }
        );

}


function renderRegionList(regionActivity) {

    const container =
        document.getElementById(
            "regionActivityList"
        );

    if (!container) {
        return;
    }

    container.innerHTML = "";

    if (
        !Array.isArray(regionActivity) ||
        regionActivity.length === 0
    ) {

        container.innerHTML =
            `
            <div class="empty-state">
                Nincs régiós aktivitási adat.
            </div>
            `;

        return;
    }

    const sorted =
        [
            ...regionActivity
        ].sort(
            (
                a,
                b
            ) =>
                Number(
                    b?.count || 0
                )
                -
                Number(
                    a?.count || 0
                )
        );

    const total =
        sorted.reduce(
            (
                sum,
                item
            ) =>
                sum
                +
                Number(
                    item?.count || 0
                ),
            0
        );

    sorted
        .slice(
            0,
            6
        )
        .forEach(
            item => {

                const count =
                    Number(
                        item?.count || 0
                    );

                const percent =
                    calculatePercent(
                        count,
                        total
                    );

                container.insertAdjacentHTML(
                    "beforeend",
                    `
                    <div class="metric-row">

                        <div class="metric-label">
                            ${escapeHtml(
                                humanizeToken(
                                    item?.region || "GLOBAL"
                                )
                            )}
                        </div>

                        <div class="metric-value">
                            ${formatNumber(
                                count
                            )}
                        </div>

                        <div class="metric-percent">
                            ${percent.toFixed(1)}%
                        </div>

                    </div>
                    `
                );

            }
        );

}


/* ==========================================================
   SOURCE ACTIVITY
========================================================== */

export function renderSourceActivity(sourceActivity) {

    renderSourceChart(
        sourceActivity
    );

    renderSourceList(
        sourceActivity
    );

}


function renderSourceChart(sourceActivity) {

    const canvas =
        document.getElementById(
            "sourceChart"
        );

    if (!canvas) {
        return;
    }

    if (sourceChartInstance) {

        sourceChartInstance.destroy();

        sourceChartInstance = null;

    }

    if (
        !Array.isArray(sourceActivity) ||
        sourceActivity.length === 0
    ) {

        return;
    }

    const labels =
        sourceActivity.map(
            item =>
                String(
                    item?.source || "UNKNOWN"
                )
        );

    const values =
        sourceActivity.map(
            item =>
                Number(
                    item?.count || 0
                )
        );

    const total =
        values.reduce(
            (
                sum,
                value
            ) => sum + value,
            0
        );

    sourceChartInstance =
        new Chart(
            canvas,
            {
                type: "doughnut",

                data: {
                    labels,

                    datasets: [
                        {
                            data:
                                values,

                            backgroundColor:
                                buildColorArray(
                                    SOURCE_COLORS,
                                    values.length
                                ),

                            borderColor:
                                "#ffffff",

                            borderWidth:
                                2,

                            hoverOffset:
                                5
                        }
                    ]
                },

                options: {

                    responsive:
                        true,

                    maintainAspectRatio:
                        false,

                    cutout:
                        "64%",

                    animation: {
                        duration:
                            650
                    },

                    plugins: {

                        legend: {
                            display:
                                false
                        },

                        tooltip: {

                            callbacks: {

                                label(
                                    context
                                ) {

                                    const value =
                                        Number(
                                            context.raw || 0
                                        );

                                    const percent =
                                        calculatePercent(
                                            value,
                                            total
                                        );

                                    return (
                                        `${context.label}: `
                                        + `${formatNumber(value)} `
                                        + `(${percent.toFixed(1)}%)`
                                    );

                                }

                            }

                        }

                    }

                }
            }
        );

}


function renderSourceList(sourceActivity) {

    const container =
        document.getElementById(
            "sourceActivityList"
        );

    if (!container) {
        return;
    }

    container.innerHTML = "";

    if (
        !Array.isArray(sourceActivity) ||
        sourceActivity.length === 0
    ) {

        container.innerHTML =
            `
            <div class="empty-state">
                Nincs forrásaktivitási adat.
            </div>
            `;

        return;
    }

    const sorted =
        [
            ...sourceActivity
        ].sort(
            (
                a,
                b
            ) =>
                Number(
                    b?.count || 0
                )
                -
                Number(
                    a?.count || 0
                )
        );

    const total =
        sorted.reduce(
            (
                sum,
                item
            ) =>
                sum
                +
                Number(
                    item?.count || 0
                ),
            0
        );

    sorted
        .slice(
            0,
            6
        )
        .forEach(
            item => {

                const count =
                    Number(
                        item?.count || 0
                    );

                const percent =
                    calculatePercent(
                        count,
                        total
                    );

                container.insertAdjacentHTML(
                    "beforeend",
                    `
                    <div class="metric-row">

                        <div class="metric-label">
                            ${escapeHtml(
                                String(
                                    item?.source || "UNKNOWN"
                                )
                            )}
                        </div>

                        <div class="metric-value">
                            ${formatNumber(
                                count
                            )}
                        </div>

                        <div class="metric-percent">
                            ${percent.toFixed(1)}%
                        </div>

                    </div>
                    `
                );

            }
        );

}


/* ==========================================================
   PROCESSING FUNNEL
========================================================== */

export function renderCorrelationMetrics(correlation) {

    const totalPosts =
        Number(
            correlation?.total_posts || 0
        );

    const operationalEvents =
        Number(
            correlation?.operational_events || 0
        );

    const correlatedSources =
        Number(
            correlation?.correlated_sources || 0
        );

    const eventGroups =
        Number(
            correlation?.event_groups || 0
        );

    const conversionRate =
        Number(
            correlation?.conversion_rate || 0
        );

    updateText(
        "correlationTotalPosts",
        formatNumber(
            totalPosts
        )
    );

    updateText(
        "correlationOperationalEvents",
        formatNumber(
            operationalEvents
        )
    );

    updateText(
        "correlationCorrelatedSources",
        formatNumber(
            correlatedSources
        )
    );

    updateText(
        "correlationEventGroups",
        formatNumber(
            eventGroups
        )
    );

    updateText(
        "conversionRate",
        formatPercent(
            conversionRate,
            2
        )
    );

    updateFunnelWidths(
        totalPosts,
        operationalEvents,
        correlatedSources,
        eventGroups
    );

}


/* ==========================================================
   FUNNEL WIDTHS
========================================================== */

function updateFunnelWidths(
    totalPosts,
    operationalEvents,
    correlatedSources,
    eventGroups
) {

    const maxValue =
        Math.max(
            totalPosts,
            1
        );

    setFunnelWidth(
        ".funnel-posts",
        totalPosts,
        maxValue,
        100
    );

    setFunnelWidth(
        ".funnel-operational",
        operationalEvents,
        maxValue,
        82
    );

    setFunnelWidth(
        ".funnel-correlated",
        correlatedSources,
        maxValue,
        64
    );

    setFunnelWidth(
        ".funnel-groups",
        eventGroups,
        maxValue,
        48
    );

}


function setFunnelWidth(
    selector,
    value,
    maxValue,
    minimumWidth
) {

    const element =
        document.querySelector(
            selector
        );

    if (!element) {
        return;
    }

    const calculated =
        calculatePercent(
            Number(
                value || 0
            ),
            Number(
                maxValue || 1
            )
        );

    const width =
        Math.max(
            minimumWidth,
            Math.min(
                calculated,
                100
            )
        );

    element.style.width =
        `${width}%`;

}


/* ==========================================================
   OPTIONAL PERFORMANCE METRICS
========================================================== */

export function getCorrelationPerformanceSummary(correlation) {

    return {

        filteringEfficiency:
            Number(
                correlation?.filtering_efficiency || 0
            ),

        operationalRate:
            Number(
                correlation?.operational_rate || 0
            ),

        correlationRate:
            Number(
                correlation?.correlation_rate || 0
            ),

        groupingRate:
            Number(
                correlation?.grouping_rate || 0
            ),

        multiSourceRate:
            Number(
                correlation?.multi_source_rate || 0
            )

    };

}


/* ==========================================================
   CHART RESET
========================================================== */

export function clearCharts() {

    if (regionChartInstance) {

        regionChartInstance.destroy();

        regionChartInstance = null;

    }

    if (sourceChartInstance) {

        sourceChartInstance.destroy();

        sourceChartInstance = null;

    }

    const regionList =
        document.getElementById(
            "regionActivityList"
        );

    if (regionList) {

        regionList.innerHTML =
            `
            <div class="empty-state">
                Adatok betöltése...
            </div>
            `;

    }

    const sourceList =
        document.getElementById(
            "sourceActivityList"
        );

    if (sourceList) {

        sourceList.innerHTML =
            `
            <div class="empty-state">
                Adatok betöltése...
            </div>
            `;

    }

}


/* ==========================================================
   HELPERS
========================================================== */

function calculatePercent(
    value,
    total
) {

    const numericValue =
        Number(
            value || 0
        );

    const numericTotal =
        Number(
            total || 0
        );

    if (
        numericTotal <= 0
    ) {
        return 0;
    }

    return (
        numericValue
        /
        numericTotal
        *
        100
    );

}


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


function buildColorArray(
    palette,
    length
) {

    const colors = [];

    for (
        let i = 0;
        i < length;
        i++
    ) {

        colors.push(
            palette[
                i %
                palette.length
            ]
        );

    }

    return colors;

}


function humanizeToken(value) {

    if (!value) {
        return "N/A";
    }

    return String(value)
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
