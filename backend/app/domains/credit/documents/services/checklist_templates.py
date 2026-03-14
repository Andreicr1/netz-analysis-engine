"""Checklist templates by document type.

Each template defines the verification items that reviewers must check
before approving a document of that type.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChecklistItemTemplate:
    category: str
    label: str
    description: str | None = None
    is_required: bool = True


CHECKLIST_TEMPLATES: dict[str, list[ChecklistItemTemplate]] = {
    "LEGAL": [
        ChecklistItemTemplate("Parties", "Borrower entity correctly identified", "Legal name, jurisdiction, registration number match term sheet"),
        ChecklistItemTemplate("Parties", "Lender/Agent entity correctly identified"),
        ChecklistItemTemplate("Governing Law", "Governing law clause present and acceptable", "Verify jurisdiction aligns with fund mandate"),
        ChecklistItemTemplate("Commercial Terms", "Interest rate and payment schedule aligned with term sheet"),
        ChecklistItemTemplate("Commercial Terms", "Maturity date and amortization schedule correct"),
        ChecklistItemTemplate("Commercial Terms", "Fees (commitment, arrangement, prepayment) match agreed terms"),
        ChecklistItemTemplate("Covenants", "Financial covenants match IC Memo conditions", "Cross-reference with IC Memo chapter 06/10"),
        ChecklistItemTemplate("Covenants", "Information covenants and reporting requirements specified"),
        ChecklistItemTemplate("Security", "Security package adequate and correctly described"),
        ChecklistItemTemplate("Security", "Perfection requirements identified"),
        ChecklistItemTemplate("Default", "Events of default section complete", "Standard and deal-specific events covered"),
        ChecklistItemTemplate("Default", "Cross-default provisions reviewed"),
        ChecklistItemTemplate("Representations", "Representations and warranties standard and complete"),
        ChecklistItemTemplate("Transfer", "Assignment/transfer restrictions acceptable", "Verify fund can transfer if needed"),
        ChecklistItemTemplate("Confidentiality", "Confidentiality clause present and workable"),
        ChecklistItemTemplate("Compliance", "Anti-money laundering provisions present"),
        ChecklistItemTemplate("Compliance", "Sanctions compliance clause included"),
    ],
    "TERM_SHEET": [
        ChecklistItemTemplate("Mandate", "Pricing within fund mandate parameters", "IRR/yield meets minimum threshold"),
        ChecklistItemTemplate("Mandate", "Ticket size within fund allocation limits"),
        ChecklistItemTemplate("Structure", "Maturity within fund investment horizon"),
        ChecklistItemTemplate("Structure", "Currency matches fund denomination (USD)"),
        ChecklistItemTemplate("Security", "Security package adequate for risk profile"),
        ChecklistItemTemplate("Security", "Collateral coverage ratio acceptable"),
        ChecklistItemTemplate("Governance", "Key person provisions present"),
        ChecklistItemTemplate("Governance", "Change of control clause included"),
        ChecklistItemTemplate("Reporting", "Reporting requirements specified", "Financial statements, compliance certificates"),
        ChecklistItemTemplate("Reporting", "Reporting frequency adequate for monitoring"),
        ChecklistItemTemplate("Exit", "Prepayment terms acceptable"),
        ChecklistItemTemplate("Exit", "Call protection period adequate"),
    ],
    "REGULATORY": [
        ChecklistItemTemplate("Filing", "Filing deadline identified and achievable"),
        ChecklistItemTemplate("Filing", "Regulatory body correctly addressed"),
        ChecklistItemTemplate("Content", "Required information complete and accurate"),
        ChecklistItemTemplate("Content", "Supporting documentation attached"),
        ChecklistItemTemplate("Signatories", "Required signatories identified", "Directors, authorized persons"),
        ChecklistItemTemplate("Signatories", "Signing authority verified"),
        ChecklistItemTemplate("Compliance", "Consistent with prior filings"),
        ChecklistItemTemplate("Compliance", "No material omissions"),
    ],
    "DD_REPORT": [
        ChecklistItemTemplate("Scope", "Due diligence scope covers all material areas"),
        ChecklistItemTemplate("Scope", "Information sources identified and reliable"),
        ChecklistItemTemplate("Financial", "Financial analysis methodology sound"),
        ChecklistItemTemplate("Financial", "Projections reasonable and stress-tested"),
        ChecklistItemTemplate("Legal", "Legal structure reviewed and acceptable"),
        ChecklistItemTemplate("Legal", "Litigation/contingent liabilities disclosed"),
        ChecklistItemTemplate("Risk", "Key risks identified and assessed"),
        ChecklistItemTemplate("Risk", "Mitigants proposed for material risks"),
        ChecklistItemTemplate("Conclusion", "Recommendation clearly stated"),
        ChecklistItemTemplate("Conclusion", "Conditions precedent identified"),
    ],
    "INVESTMENT_MEMO": [
        ChecklistItemTemplate("Impact", "Impact on existing covenants assessed"),
        ChecklistItemTemplate("Impact", "Financial model updated with amendment terms"),
        ChecklistItemTemplate("Approval", "IC re-approval required?", "Flag if material change to approved terms", is_required=False),
        ChecklistItemTemplate("Approval", "Borrower consent obtained or pending"),
        ChecklistItemTemplate("Documentation", "Amendment document reviewed by legal"),
        ChecklistItemTemplate("Documentation", "Side letter terms (if any) documented"),
        ChecklistItemTemplate("Monitoring", "Updated monitoring parameters identified"),
    ],
    "MARKETING": [
        ChecklistItemTemplate("Accuracy", "Performance figures accurate and sourced"),
        ChecklistItemTemplate("Accuracy", "Fund terms correctly represented"),
        ChecklistItemTemplate("Compliance", "Regulatory disclaimers present", "Risk warnings, past performance caveat"),
        ChecklistItemTemplate("Compliance", "No misleading statements or projections"),
        ChecklistItemTemplate("Branding", "Consistent with fund branding guidelines", is_required=False),
    ],
    "OTHER": [
        ChecklistItemTemplate("General", "Document purpose clearly stated"),
        ChecklistItemTemplate("General", "Content accurate and complete"),
        ChecklistItemTemplate("General", "No confidential information improperly disclosed", is_required=False),
    ],
}


def get_checklist_template(document_type: str) -> list[ChecklistItemTemplate]:
    """Return the checklist template for a document type, falling back to OTHER."""
    return CHECKLIST_TEMPLATES.get(document_type, CHECKLIST_TEMPLATES["OTHER"])
