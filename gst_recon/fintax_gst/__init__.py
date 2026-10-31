"""FIN TAX PRO – Smart GST Reconciliation & ITC Management System.

The package is layered so that the reconciliation engine has no dependency on
the database, the desktop UI or any web framework:

    core/        pure domain types, money and GSTIN/invoice-number rules
    engine/      deterministic reconciliation engine and summaries
    importers/   file readers, layout detection, column mapping, validation
    db/          SQLAlchemy models, migrations and session handling
    services/    application use-cases (clients, imports, reconciliation runs)
    reports/     Excel and PDF report generation
    ui/          PySide6 desktop interface (Phase 2)
"""

PRODUCT_NAME = "FIN TAX PRO"
PRODUCT_FULL_NAME = "FIN TAX PRO – Smart GST Reconciliation & ITC Management System"
TAGLINE = "Smart GST Reconciliation. Faster Compliance. Better Accuracy."
__version__ = "1.3.0"
ENGINE_VERSION = "1.0.0"
