"use client";

import { useState, useRef, useEffect } from "react";
import "../courtroom.css";

// Simple UUID v4 generator (no external dependency)
const generateUUID = () => {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
};

export default function CourtroomPage() {
  const [phase, setPhase] = useState("case-select"); // case-select, case-details, debating, results
  const [caseData, setCaseData] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [debate, setDebate] = useState([]);
  const [userInput, setUserInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState("");
  const debateEndRef = useRef(null);

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    debateEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [debate]);

  // Dummy case scenarios (in production, load from backend)
  const SAMPLE_CASES = [
    {
      id: "case-01",
      title: "State vs. Rajesh Kumar - Theft Case",
      description: "A 45-year-old man accused of stealing from a retail store.",
      caseDetails: {
        victim: "ABC Retail Store Pvt Ltd",
        accused: "Rajesh Kumar, Age 45",
        charges: ["Theft under IPC Section 379", "Criminal intimidation under Section 503"],
        evidence: [
          "CCTV footage showing accused taking items",
          "Witness statement from store manager",
          "Accused was found with stolen goods worth ₹15,000",
        ],
        victimStatement: "The accused entered our store on 15th March 2024 at 2:30 PM and took electronic items worth ₹15,000 without paying. When confronted, he became aggressive and threatened the staff.",
        policeReport: "Initial investigation shows clear evidence. Accused has prior record of similar offences.",
        courtProcedure: "You are the defense lawyer. Make arguments in favor of the accused.",
      },
    },
    {
      id: "case-02",
      title: "Employee vs. XYZ Corp - Wrongful Termination",
      description: "A case of alleged wrongful termination by a private company.",
      caseDetails: {
        victim: "Priya Sharma, Employee",
        accused: "XYZ Corporation Ltd",
        charges: ["Wrongful termination", "Breach of employment contract"],
        evidence: [
          "Employment contract dated 2020 with 3-month notice period clause",
          "Email evidence of termination without notice",
          "Performance reviews showing satisfactory ratings",
        ],
        victimStatement: "I was terminated without any prior warning or notice. I had consistently received good performance reviews and was never given any chance to improve. This is clearly unfair.",
        policeReport: "Company claims restructuring, but legal procedures not followed.",
        courtProcedure: "You are the employee's lawyer. Build a case against the wrongful termination.",
      },
    },
    {
      id: "case-03",
      title: "Vs. Local Authority - Land Dispute",
      description: "A property land dispute with local municipal authorities.",
      caseDetails: {
        victim: "Property Owner - Ravi Patel",
        accused: "Municipal Corporation XYZ",
        charges: ["Unjust land seizure", "Violation of Property Rights"],
        evidence: [
          "Original property deed from 1995",
          "Tax payment receipts for 20+ years",
          "Published municipal notice (with allegations of illegal encroachment)",
        ],
        victimStatement: "My family has owned this land for over 20 years. We have all legal documents and have been paying property taxes. Suddenly the municipality seized it claiming it's public land.",
        policeReport: "Municipal authority claims the property was illegally encroached. Property owner disputes the claim.",
        courtProcedure: "You are the property owner's lawyer. Defend the rightful ownership.",
      },
    },
  ];

  const handleSelectCase = async (caseId) => {
    const selected = SAMPLE_CASES.find((c) => c.id === caseId);
    if (!selected) return;

    setCaseData(selected);
    setPhase("case-details");
    setError("");
  };

  const handleStartDebate = async () => {
    if (!caseData) return;

    setIsLoading(true);
    setError("");

    try {
      const newSessionId = generateUUID();
      setSessionId(newSessionId);

      const response = await fetch("/api/courtroom/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: newSessionId,
          case_id: caseData.id,
          case_details: caseData.caseDetails,
        }),
      });

      if (!response.ok) {
        let message = "Failed to start courtroom session";
        try {
          const payload = await response.json();
          if (payload?.error) message = payload.error;
        } catch {
          // Keep fallback message if response body is not JSON.
        }
        throw new Error(message);
      }

      const data = await response.json();
      setDebate(data.opening || []);
      setPhase("debating");
    } catch (err) {
      setError(err.message || "Error starting courtroom session");
      setIsLoading(false);
    }
  };

  const handleSubmitArgument = async () => {
    if (!userInput.trim() || !sessionId) return;

    const studentArgument = userInput;
    setUserInput("");
    setIsLoading(true);
    setError("");

    try {
      // Add student input to debate
      const newDebate = [...debate, { speaker: "You (Defense Lawyer)", text: studentArgument, type: "student" }];
      setDebate(newDebate);

      const response = await fetch("/api/courtroom/turn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          student_argument: studentArgument,
        }),
      });

      if (!response.ok) {
        let message = "Failed to get courtroom response";
        try {
          const payload = await response.json();
          if (payload?.error) message = payload.error;
        } catch {
          // Keep fallback message if response body is not JSON.
        }
        throw new Error(message);
      }

      const data = await response.json();

      // Add judge and opposing lawyer responses
      if (data.judge_response) {
        newDebate.push({
          speaker: "Judge",
          text: data.judge_response,
          type: "judge",
        });
      }

      if (data.lawyer_response) {
        newDebate.push({
          speaker: "Opposing Lawyer",
          text: data.lawyer_response,
          type: "opposing",
        });
      }

      setDebate(newDebate);
      setIsLoading(false);

      // Check if courtroom should end (after 8 turns)
      if (newDebate.length > 15) {
        setTimeout(() => handleEndDebate(), 3000);
      }
    } catch (err) {
      setError(err.message || "Error processing argument");
      setIsLoading(false);
    }
  };

  const handleEndDebate = async () => {
    if (!sessionId) return;

    setIsLoading(true);
    setError("");

    try {
      const response = await fetch("/api/courtroom/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
        }),
      });

      if (!response.ok) {
        let message = "Failed to evaluate courtroom performance";
        try {
          const payload = await response.json();
          if (payload?.error) message = payload.error;
        } catch {
          // Keep fallback message if response body is not JSON.
        }
        throw new Error(message);
      }

      const data = await response.json();
      setStats(data.stats);
      setPhase("results");
    } catch (err) {
      setError(err.message || "Error evaluating performance");
    } finally {
      setIsLoading(false);
    }
  };

  const handleRestart = () => {
    setPhase("case-select");
    setCaseData(null);
    setSessionId(null);
    setDebate([]);
    setUserInput("");
    setStats(null);
    setError("");
  };

  return (
    <div className="courtroom-container">
      {/* Case Selection Phase */}
      {phase === "case-select" && (
        <div className="phase-panel case-selection">
          <div className="phase-header">
            <h1>Virtual Courtroom</h1>
            <p>Select a case scenario to begin your legal practice debate</p>
          </div>

          <div className="cases-grid">
            {SAMPLE_CASES.map((caseItem) => (
              <div
                key={caseItem.id}
                className="case-card"
                onClick={() => handleSelectCase(caseItem.id)}
              >
                <h3>{caseItem.title}</h3>
                <p>{caseItem.description}</p>
                <button className="case-select-btn">Select Case →</button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Case Details Phase */}
      {phase === "case-details" && caseData && (
        <div className="phase-panel case-details">
          <div className="case-header">
            <h2>{caseData.title}</h2>
            <button className="back-btn" onClick={() => setPhase("case-select")}>← Back</button>
          </div>

          <div className="case-content">
            <div className="case-section">
              <h3>Case Overview</h3>
              <div className="detail-group">
                <span className="label">Accused:</span>
                <span>{caseData.caseDetails.accused}</span>
              </div>
              <div className="detail-group">
                <span className="label">Charges:</span>
                <ul>
                  {caseData.caseDetails.charges.map((charge, i) => (
                    <li key={i}>{charge}</li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="case-section">
              <h3>Victim Statement</h3>
              <p className="statement">{caseData.caseDetails.victimStatement}</p>
            </div>

            <div className="case-section">
              <h3>Evidence</h3>
              <ul className="evidence-list">
                {caseData.caseDetails.evidence.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>

            <div className="case-section">
              <h3>Police Report</h3>
              <p>{caseData.caseDetails.policeReport}</p>
            </div>

            <div className="case-section instruction">
              <h3>Your Role</h3>
              <p>{caseData.caseDetails.courtProcedure}</p>
            </div>

            <button
              className="start-debate-btn"
              onClick={handleStartDebate}
              disabled={isLoading}
            >
              {isLoading ? "Starting..." : "Start Courtroom Debate →"}
            </button>
          </div>
        </div>
      )}

      {/* Debate Phase */}
      {phase === "debating" && (
        <div className="phase-panel debate-phase">
          <div className="debate-header">
            <h2>{caseData?.title}</h2>
            <div className="debate-stats">
              <span>{Math.floor(debate.length / 2)} rounds</span>
            </div>
          </div>

          <div className="debate-transcript">
            {debate.map((msg, idx) => (
              <div key={idx} className={`debate-message ${msg.type}`}>
                <div className="speaker-badge">{msg.speaker}</div>
                <div className="message-text">{msg.text}</div>
              </div>
            ))}
            {isLoading && (
              <div className="debate-message loading">
                <div className="speaker-badge">Courtroom</div>
                <div className="message-text">
                  <span className="typing-indicator">●●●</span>
                </div>
              </div>
            )}
            <div ref={debateEndRef} />
          </div>

          <div className="argument-input">
            <textarea
              value={userInput}
              onChange={(e) => setUserInput(e.target.value)}
              placeholder="Present your legal argument or response..."
              disabled={isLoading}
              onKeyDown={(e) => {
                if (e.ctrlKey && e.key === "Enter") {
                  handleSubmitArgument();
                }
              }}
            />
            <div className="input-actions">
              <button
                onClick={handleSubmitArgument}
                disabled={!userInput.trim() || isLoading}
                className="submit-btn"
              >
                Submit Argument
              </button>
              <button
                onClick={handleEndDebate}
                disabled={isLoading}
                className="end-btn"
              >
                End Debate
              </button>
            </div>
          </div>

          {error && <div className="error-message">{error}</div>}
        </div>
      )}

      {/* Results Phase */}
      {phase === "results" && stats && (
        <div className="phase-panel results-phase">
          <div className="results-header">
            <h2>Performance Evaluation</h2>
            <p>Case: {caseData?.title}</p>
          </div>

          <div className="stats-container">
            <div className="stat-card">
              <div className="stat-label">Legal Reasoning Score</div>
              <div className="stat-value">{stats.legal_reasoning_score}%</div>
              <div className="stat-bar">
                <div
                  className="stat-fill"
                  style={{ width: `${stats.legal_reasoning_score}%` }}
                ></div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-label">Argument Strength</div>
              <div className="stat-value">{stats.argument_strength}%</div>
              <div className="stat-bar">
                <div
                  className="stat-fill"
                  style={{ width: `${stats.argument_strength}%` }}
                ></div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-label">Courtroom Procedure</div>
              <div className="stat-value">{stats.procedure_score}%</div>
              <div className="stat-bar">
                <div
                  className="stat-fill"
                  style={{ width: `${stats.procedure_score}%` }}
                ></div>
              </div>
            </div>

            <div className="stat-card overall">
              <div className="stat-label">Overall Performance</div>
              <div className="stat-value">{stats.overall_score}%</div>
              <div className="stat-grade">{stats.grade}</div>
            </div>
          </div>

          {stats.feedback && (
            <div className="feedback-section">
              <h3>Feedback</h3>
              <p>{stats.feedback}</p>
            </div>
          )}

          {stats.strengths && stats.strengths.length > 0 && (
            <div className="strengths-section">
              <h3>✓ Strengths</h3>
              <ul>
                {stats.strengths.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </div>
          )}

          {stats.areas_to_improve && stats.areas_to_improve.length > 0 && (
            <div className="improvements-section">
              <h3>→ Areas to Improve</h3>
              <ul>
                {stats.areas_to_improve.map((area, i) => (
                  <li key={i}>{area}</li>
                ))}
              </ul>
            </div>
          )}

          <button className="restart-btn" onClick={handleRestart}>
            Try Another Case
          </button>
        </div>
      )}

      {error && phase !== "debating" && (
        <div className="error-banner">{error}</div>
      )}
    </div>
  );
}
