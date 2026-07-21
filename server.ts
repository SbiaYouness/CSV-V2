import express from "express";
import path from "path";
import { spawn } from "child_process";
import { GoogleGenAI } from "@google/genai";
import { createServer as createViteServer } from "vite";

// ─── Gemini API client ──────────────────────────────────────────────────────
let aiClient: GoogleGenAI | null = null;
function getAIClient(): GoogleGenAI {
  if (!aiClient) {
    const key = process.env.GEMINI_API_KEY;
    if (!key) {
      console.warn("WARNING: GEMINI_API_KEY is not defined. AI Summary will fail.");
    }
    aiClient = new GoogleGenAI({ apiKey: key || "PLACEHOLDER" });
  }
  return aiClient;
}

// In-memory summary cache to hold details of processed reconciliations
const _SUMMARY_CONTEXTS = new Map<string, any>();

async function startServer() {
  const app = express();
  const PORT = 3000;

  console.log("Starting Python FastAPI backend...");
  const pythonProcess = spawn("python3", ["-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8500"], {
    cwd: path.join(process.cwd(), "backend"),
    env: { ...process.env, PYTHONUNBUFFERED: "1" }
  });

  pythonProcess.stdout.on("data", (data) => {
    console.log(`[Python Backend] ${data.toString().trim()}`);
  });

  pythonProcess.stderr.on("data", (data) => {
    console.error(`[Python Backend ERROR] ${data.toString().trim()}`);
  });

  pythonProcess.on("close", (code) => {
    console.log(`Python backend exited with code ${code}`);
  });

  // Ensure child python process is killed on node exit
  process.on("exit", () => {
    pythonProcess.kill();
  });
  process.on("SIGINT", () => {
    pythonProcess.kill();
    process.exit(0);
  });
  process.on("SIGTERM", () => {
    pythonProcess.kill();
    process.exit(0);
  });

  // ─── API Gateway / Proxies ────────────────────────────────────────────────
  
  // GET /api/files
  app.get("/api/files", async (req, res) => {
    try {
      const response = await fetch("http://127.0.0.1:8500/api/files");
      if (!response.ok) {
        throw new Error(`FastAPI response not OK: ${response.status}`);
      }
      const data = await response.json();
      res.json(data);
    } catch (err) {
      console.error("Failed to proxy /api/files:", err);
      res.status(502).json({ error: "Failed to connect to backend", details: String(err) });
    }
  });

  // POST /api/reconcile
  app.post("/api/reconcile", express.json({ limit: "50mb" }), async (req, res) => {
    try {
      const response = await fetch("http://127.0.0.1:8500/api/reconcile", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(req.body),
      });
      if (!response.ok) {
        const errText = await response.text();
        throw new Error(`FastAPI responded with ${response.status}: ${errText}`);
      }
      const data = await response.json();

      // Store summary context in-memory so we can build a perfect summary on demand
      if (data && data.id) {
        const badRows = (data.transactions || []).filter((tx: any) => {
          const status = tx.Statut || "";
          return status !== "OK" && !status.includes("non disponible") && !status.includes("Pas de PDF");
        });

        _SUMMARY_CONTEXTS.set(data.id, {
          matched: data.summary?.matched || 0,
          mismatched: data.summary?.ecart || 0,
          pdf_only: data.summary?.pdfOnly || 0,
          csv_only: data.summary?.csvOnly || 0,
          score: data.complianceScore || 0,
          details: badRows.slice(0, 30),
        });
      }

      res.json(data);
    } catch (err) {
      console.error("Failed to proxy /api/reconcile:", err);
      res.status(502).json({ error: "Reconciliation failed", details: String(err) });
    }
  });

  // POST /api/summary - Server-side Gemini AI summary integration
  app.post("/api/summary", express.json(), async (req, res) => {
    try {
      const { result_id } = req.body;
      if (!result_id) {
        return res.status(400).json({ error: "Missing result_id" });
      }

      const ctx = _SUMMARY_CONTEXTS.get(result_id);
      if (!ctx) {
        return res.status(404).json({ error: "Contexte introuvable. Relancez le rapprochement." });
      }

      const prompt = `
Tu es un analyste financier senior spécialisé dans l'audit et le rapprochement de données réglementaires de conformité bancaire (Piliers EBA).

Voici le bilan du rapprochement effectué entre le classeur interne et les publications officielles PDF :
- Lignes parfaitement concordantes : ${ctx.matched}
- Écarts significatifs détectés : ${ctx.mismatched}
- Éléments non trouvés dans le PDF : ${ctx.pdf_only}
- Score de conformité globale : ${ctx.score}%

Détails clés des anomalies d'écarts observées (uniquement les principaux cas) :
${ctx.details.length > 0 ? JSON.stringify(ctx.details.map((d: any) => ({
  entite: d.Entité,
  indicateur: d.Indicateur,
  valeur_interne: d["Valeur resultats"],
  valeur_pdf: d["Valeur PDF (EBA)"],
  difference: d.Ecart,
  statut: d.Statut
}))) : "Aucun écart significatif majeur détecté."}

Rédige une synthèse d'audit concise et rigoureuse en français (maximum 6 phrases).
Explique de manière synthétique la nature générale des écarts (par exemple, problème d'unité ou de périmètre) et propose une action corrective précise pour corriger la déclaration réglementaire.
`;

      const ai = getAIClient();
      const response = await ai.models.generateContent({
        model: "gemini-2.5-flash",
        contents: prompt,
      });

      const synthesis = response.text || "Synthèse indisponible.";
      res.json({ aiSynthesis: synthesis });
    } catch (err) {
      console.error("AI summary generation error:", err);
      res.status(500).json({ error: "Failed to generate AI synthesis", details: String(err) });
    }
  });

  // ─── Frontend Dev Middleware & Production static files ─────────────────────
  if (process.env.NODE_ENV !== "production") {
    console.log("Starting Vite development server inside Express...");
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
      root: path.join(process.cwd(), "frontend"),
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "frontend", "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://0.0.0.0:${PORT}`);
  });
}

startServer();
