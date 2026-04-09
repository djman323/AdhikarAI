"use client";

import { useMemo, useState } from "react";
import "../contracts.css";

const CONTRACT_TYPES = [
  "Employment Agreement",
  "Non-Disclosure Agreement (NDA)",
  "Service Agreement",
  "Freelance Contract",
  "Lease Agreement",
  "Vendor Agreement",
  "Partnership Agreement",
  "Consulting Agreement",
];

const GOVERNING_LAW_OPTIONS = [
  "Laws of India",
  "Laws of Maharashtra, India",
  "Laws of Karnataka, India",
  "Laws of Delhi, India",
  "Custom",
];

const DEFAULT_FORM = {
  contractType: "Employment Agreement",
  partyOneName: "",
  partyOneRole: "",
  partyTwoName: "",
  partyTwoRole: "",
  effectiveDate: "",
  termDuration: "",
  scopeOfWork: "",
  paymentTerms: "",
  confidentialityTerms: "",
  terminationClause: "",
  disputeResolution: "Arbitration in India",
  governingLaw: "Laws of India",
  governingLawCustom: "",
  additionalClauses: "",
};

function requiredLabel(text) {
  return (
    <span>
      {text} <strong className="contracts-required">*</strong>
    </span>
  );
}

function sanitize(value) {
  return (value || "").trim() || "[To be filled]";
}

function buildContractDraft(form) {
  const governingLaw =
    form.governingLaw === "Custom" ? sanitize(form.governingLawCustom) : sanitize(form.governingLaw);

  return `
${sanitize(form.contractType).toUpperCase()}

This ${sanitize(form.contractType)} ("Agreement") is made and entered into on ${sanitize(form.effectiveDate)} ("Effective Date") between:

1. ${sanitize(form.partyOneName)} (${sanitize(form.partyOneRole)})
2. ${sanitize(form.partyTwoName)} (${sanitize(form.partyTwoRole)})

Collectively referred to as the "Parties".

1. PURPOSE
The Parties agree to enter into this Agreement for the purpose of defining their professional and legal relationship under the terms stated herein.

2. TERM
This Agreement shall commence from the Effective Date and shall remain in force for ${sanitize(form.termDuration)}, unless terminated earlier in accordance with this Agreement.

3. SCOPE OF WORK / OBLIGATIONS
${sanitize(form.scopeOfWork)}

4. PAYMENT / CONSIDERATION
${sanitize(form.paymentTerms)}

5. CONFIDENTIALITY
${sanitize(form.confidentialityTerms)}

6. TERMINATION
${sanitize(form.terminationClause)}

7. DISPUTE RESOLUTION
Any dispute arising out of or in connection with this Agreement shall be resolved by ${sanitize(form.disputeResolution)}.

8. GOVERNING LAW
This Agreement shall be governed by and construed in accordance with ${governingLaw}.

9. ADDITIONAL CLAUSES
${sanitize(form.additionalClauses)}

10. ENTIRE AGREEMENT
This Agreement constitutes the entire understanding between the Parties and supersedes all prior oral or written understandings in relation to the subject matter.

11. SIGNATURES
IN WITNESS WHEREOF, the Parties have executed this Agreement on the Effective Date.

Party 1 Signature: ______________________
Name: ${sanitize(form.partyOneName)}
Date: ______________________

Party 2 Signature: ______________________
Name: ${sanitize(form.partyTwoName)}
Date: ______________________

---
Drafting note: This is a first draft for professional use. Have a licensed advocate review it before execution.
`.trim();
}

export default function ContractsPage() {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [draft, setDraft] = useState("");
  const [copied, setCopied] = useState(false);

  const canGenerate = useMemo(() => {
    return (
      form.contractType &&
      form.partyOneName.trim() &&
      form.partyTwoName.trim() &&
      form.effectiveDate.trim() &&
      form.scopeOfWork.trim()
    );
  }, [form]);

  const updateField = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setCopied(false);
  };

  const handleGenerate = (e) => {
    e.preventDefault();
    if (!canGenerate) {
      setDraft("Please fill all mandatory fields to generate a draft.");
      return;
    }
    setDraft(buildContractDraft(form));
  };

  const handleReset = () => {
    setForm(DEFAULT_FORM);
    setDraft("");
    setCopied(false);
  };

  const handleCopy = async () => {
    if (!draft) return;
    try {
      await navigator.clipboard.writeText(draft);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  const buildFileBaseName = () => {
    const type = (form.contractType || "contract")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    const datePart = form.effectiveDate || new Date().toISOString().slice(0, 10);
    return `${type || "contract"}-${datePart}`;
  };

  const triggerDownload = (content, fileName, mimeType) => {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleDownloadTxt = () => {
    if (!draft) return;
    const fileName = `${buildFileBaseName()}.txt`;
    triggerDownload(draft, fileName, "text/plain;charset=utf-8");
  };

  const handleDownloadDoc = () => {
    if (!draft) return;
    const fileName = `${buildFileBaseName()}.doc`;
    const escaped = draft
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\n/g, "<br>");
    const docHtml = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Contract Draft</title>
  <style>
    body { font-family: 'Times New Roman', serif; font-size: 12pt; line-height: 1.45; margin: 1in; }
  </style>
</head>
<body>
  ${escaped}
</body>
</html>`;
    triggerDownload(docHtml, fileName, "application/msword;charset=utf-8");
  };

  return (
    <main className="contracts-shell">
      <section className="contracts-hero">
        <p className="contracts-kicker">Professional drafting workspace</p>
        <h1>Draft legal and business contracts in minutes</h1>
        <p>
          Build a structured first draft with Indian legal context, then refine and validate with a qualified legal
          professional before signing.
        </p>
      </section>

      <section className="contracts-grid">
        <form className="contracts-form" onSubmit={handleGenerate}>
          <div className="contracts-card contracts-card--intro">
            <h2>Contract Details</h2>
            <p>Fill the key terms to generate a legally structured draft.</p>
          </div>

          <div className="contracts-card">
            <label>{requiredLabel("Contract Type")}</label>
            <select value={form.contractType} onChange={(e) => updateField("contractType", e.target.value)}>
              {CONTRACT_TYPES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>

          <div className="contracts-card contracts-card--two-col">
            <div>
              <label>{requiredLabel("Party 1 Name")}</label>
              <input
                type="text"
                value={form.partyOneName}
                onChange={(e) => updateField("partyOneName", e.target.value)}
                placeholder="ABC Pvt Ltd"
              />
            </div>
            <div>
              <label>Party 1 Role</label>
              <input
                type="text"
                value={form.partyOneRole}
                onChange={(e) => updateField("partyOneRole", e.target.value)}
                placeholder="Employer / Client / Lessor"
              />
            </div>
          </div>

          <div className="contracts-card contracts-card--two-col">
            <div>
              <label>{requiredLabel("Party 2 Name")}</label>
              <input
                type="text"
                value={form.partyTwoName}
                onChange={(e) => updateField("partyTwoName", e.target.value)}
                placeholder="John Doe"
              />
            </div>
            <div>
              <label>Party 2 Role</label>
              <input
                type="text"
                value={form.partyTwoRole}
                onChange={(e) => updateField("partyTwoRole", e.target.value)}
                placeholder="Employee / Consultant / Lessee"
              />
            </div>
          </div>

          <div className="contracts-card contracts-card--two-col">
            <div>
              <label>{requiredLabel("Effective Date")}</label>
              <input type="date" value={form.effectiveDate} onChange={(e) => updateField("effectiveDate", e.target.value)} />
            </div>
            <div>
              <label>Term / Duration</label>
              <input
                type="text"
                value={form.termDuration}
                onChange={(e) => updateField("termDuration", e.target.value)}
                placeholder="12 months / until project completion"
              />
            </div>
          </div>

          <div className="contracts-card">
            <label>{requiredLabel("Scope of Work / Obligations")}</label>
            <textarea
              value={form.scopeOfWork}
              onChange={(e) => updateField("scopeOfWork", e.target.value)}
              placeholder="Describe deliverables, responsibilities, and compliance obligations."
            />
          </div>

          <div className="contracts-card">
            <label>Payment Terms</label>
            <textarea
              value={form.paymentTerms}
              onChange={(e) => updateField("paymentTerms", e.target.value)}
              placeholder="Mention fees, invoice cycle, payment due date, late fee, taxes."
            />
          </div>

          <div className="contracts-card">
            <label>Confidentiality Terms</label>
            <textarea
              value={form.confidentialityTerms}
              onChange={(e) => updateField("confidentialityTerms", e.target.value)}
              placeholder="Define confidential information, non-disclosure obligations, and exceptions."
            />
          </div>

          <div className="contracts-card">
            <label>Termination Clause</label>
            <textarea
              value={form.terminationClause}
              onChange={(e) => updateField("terminationClause", e.target.value)}
              placeholder="Notice period, breach, convenience termination, post-termination duties."
            />
          </div>

          <div className="contracts-card contracts-card--two-col">
            <div>
              <label>Dispute Resolution</label>
              <input
                type="text"
                value={form.disputeResolution}
                onChange={(e) => updateField("disputeResolution", e.target.value)}
                placeholder="Arbitration in Mumbai under Arbitration and Conciliation Act"
              />
            </div>
            <div>
              <label>Governing Law</label>
              <select value={form.governingLaw} onChange={(e) => updateField("governingLaw", e.target.value)}>
                {GOVERNING_LAW_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {form.governingLaw === "Custom" && (
            <div className="contracts-card">
              <label>Custom Governing Law</label>
              <input
                type="text"
                value={form.governingLawCustom}
                onChange={(e) => updateField("governingLawCustom", e.target.value)}
                placeholder="e.g., Laws of Gujarat, India"
              />
            </div>
          )}

          <div className="contracts-card">
            <label>Additional Clauses</label>
            <textarea
              value={form.additionalClauses}
              onChange={(e) => updateField("additionalClauses", e.target.value)}
              placeholder="Include indemnity, non-compete, force majeure, IP ownership, etc."
            />
          </div>

          <div className="contracts-actions">
            <button type="submit" className="contracts-btn contracts-btn--primary" disabled={!canGenerate}>
              Generate Draft
            </button>
            <button type="button" className="contracts-btn contracts-btn--ghost" onClick={handleReset}>
              Reset
            </button>
          </div>
        </form>

        <section className="contracts-output">
          <div className="contracts-card contracts-card--intro">
            <h2>Draft Output</h2>
            <p>Copy and edit this first draft, then get it reviewed by a licensed legal professional.</p>
          </div>

          <div className="contracts-draft-box" role="region" aria-label="Generated contract draft">
            {draft ? <pre>{draft}</pre> : <p className="contracts-placeholder">Your generated contract draft will appear here.</p>}
          </div>

          <div className="contracts-actions">
            <button
              type="button"
              className="contracts-btn contracts-btn--primary"
              onClick={handleCopy}
              disabled={!draft}
            >
              {copied ? "Copied" : "Copy Draft"}
            </button>
            <button
              type="button"
              className="contracts-btn contracts-btn--ghost"
              onClick={handleDownloadTxt}
              disabled={!draft}
            >
              Download TXT
            </button>
            <button
              type="button"
              className="contracts-btn contracts-btn--ghost"
              onClick={handleDownloadDoc}
              disabled={!draft}
            >
              Download DOC
            </button>
          </div>

          <div className="contracts-note">
            <strong>Important:</strong> This tool creates a drafting baseline. It is not a substitute for professional legal advice.
          </div>
        </section>
      </section>
    </main>
  );
}
