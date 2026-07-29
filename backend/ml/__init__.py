"""
The machine-learning layer, split by what each module answers.

    features.py         encode raw indicators into the model's feature row
    registry.py         load the scaler and estimators once per process
    versioning.py       which artifacts are loaded, for the audit trail
    applicability.py    is this patient inside the training envelope?
    percentile.py       where this estimate sits among comparable patients
    explain.py          per-patient SHAP attribution
    figures.py          the SHAP waterfall figure
    counterfactuals.py  what would change this estimate
    pdf.py              the multi-page clinical report
    charts.py           palette, axes styling, PNG output

These were one 626-line module called `clinical.py`. Six unrelated jobs sharing a file
means a change to the PDF layout sits next to the extrapolation rules, and a reader
looking for either has to skim past the other five.

Nothing is re-exported here. Import the module that does the job — `from backend.ml
import applicability` — so a reader of any call site can see which concern is in play
without opening this file.
"""
