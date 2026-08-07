/*
==========================================================
Migration OSINT Dashboard

File:
js/kpi.js

Description:
Renders the KPI cards.

Dependencies:
utils.js

==========================================================
*/

"use strict";

import {
    formatNumber,
    safeValue
} from "./utils.js";


const KPI_MAP = {

    operational_events:
        "kpiOperationalEvents",

    new_events:
        "kpiNewEvents",

    correlated_events:
        "kpiCorrelatedEvents",

    active_event_groups:
        "kpiActiveEventGroups",

    sources:
        "kpiSources",

    regions:
        "kpiRegions"

};


/* ==========================================================
   PUBLIC
========================================================== */

export function renderKpis(data) {

    if (
        !data ||
        !data.kpis
    ) {
        clearKpis();
        return;
    }

    const kpis =
        data.kpis;

    updateKpi(
        KPI_MAP.operational_events,
        kpis.operational_events
    );

    updateKpi(
        KPI_MAP.new_events,
        kpis.new_events
    );

    updateKpi(
        KPI_MAP.correlated_events,
        kpis.correlated_events
    );

    updateKpi(
        KPI_MAP.active_event_groups,
        kpis.active_event_groups
    );

    updateKpi(
        KPI_MAP.sources,
        kpis.sources
    );

    updateKpi(
        KPI_MAP.regions,
        kpis.regions
    );

}


/* ==========================================================
   PRIVATE
========================================================== */

function updateKpi(
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
        formatNumber(
            safeValue(
                value,
                0
            )
        );

}


export function clearKpis() {

    Object.values(KPI_MAP)
        .forEach(
            id => {

                const element =
                    document.getElementById(
                        id
                    );

                if (
                    element
                ) {

                    element.textContent =
                        "-";

                }

            }
        );

}


/* ==========================================================
   ANIMATION
========================================================== */

export function animateKpis(data) {

    if (
        !data ||
        !data.kpis
    ) {

        clearKpis();

        return;

    }

    Object.entries(KPI_MAP)
        .forEach(
            ([key, id]) => {

                animateValue(
                    id,
                    Number(
                        data.kpis[key] || 0
                    )
                );

            }
        );

}


function animateValue(
    elementId,
    target
) {

    const element =
        document.getElementById(
            elementId
        );

    if (!element) {
        return;
    }

    const duration =
        700;

    const frameRate =
        20;

    const steps =
        duration / frameRate;

    const increment =
        target / steps;

    let current = 0;

    const interval =
        setInterval(
            () => {

                current += increment;

                if (
                    current >= target
                ) {

                    current =
                        target;

                    clearInterval(
                        interval
                    );

                }

                element.textContent =
                    formatNumber(
                        Math.round(
                            current
                        )
                    );

            },
            frameRate
        );

}
