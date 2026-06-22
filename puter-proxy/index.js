const express = require('express');
const cors = require('cors');
const bodyParser = require('body-parser');
const puter = require('@heyputer/puter.js').puter;
require('dotenv').config();

const app = express();
const port = process.env.PORT || 8080;

app.use(cors());
app.use(bodyParser.json());

console.log("[DEBUG] Puter keys:", Object.keys(puter));
console.log("[DEBUG] Puter.ai:", puter.ai);

// Initialize Puter with the token
const PUTER_TOKEN = process.env.PUTER_TOKEN;

if (!PUTER_TOKEN) {
    console.warn("⚠️  PUTER_TOKEN is not set in .env. Headless mode might fail unless you authenticate via browser first.");
} else {
    puter.setAuthToken(PUTER_TOKEN);
}

// Health Check
app.get('/v1/models', (req, res) => {
    res.json({
        data: [
            { id: "claude-3-5-sonnet", object: "model", created: 1715000000, owned_by: "anthropic" },
            { id: "claude-3-opus", object: "model", created: 1715000000, owned_by: "anthropic" }
        ]
    });
});

// OpenAI-compatible Chat Completions
app.post('/v1/chat/completions', async (req, res) => {
    const { model, messages, stream } = req.body;

    console.log(`[PROXY] Request received for model: ${model}`);
    
    // Diagnostic check at runtime
    if (!puter) {
        console.error("[CRITICAL] 'puter' object is missing at runtime!");
        return res.status(500).json({ error: "SDK Instance lost" });
    }
    if (!puter.ai) {
        console.error("[CRITICAL] 'puter.ai' is missing at runtime! Current keys:", Object.keys(puter));
        return res.status(500).json({ error: "AI module not initialized" });
    }

    try {
        if (stream) {
            res.status(501).send({ error: "Streaming not yet implemented" });
            return;
        }

        console.log(`[${new Date().toISOString()}] [PROXY] Calling puter.ai.chat with ${messages.length} messages...`);
        const startTime = Date.now();
        
        // Call Puter AI
        const puterResponse = await puter.ai.chat(messages, {
            model: model || 'claude-sonnet-4'
        });

        const duration = Date.now() - startTime;
        console.log(`[${new Date().toISOString()}] [PROXY] Raw Puter Response (Took ${duration}ms):`, JSON.stringify(puterResponse, null, 2));

        // Check for error in the response itself
        if (puterResponse.message && puterResponse.code) {
            console.error("[PROXY ERROR] Puter returned an error:", puterResponse.message);
            return res.status(401).json({
                error: {
                    message: puterResponse.message,
                    code: puterResponse.code,
                    type: "puter_auth_error"
                }
            });
        }

        console.log("[PROXY] Success! Formatting response...");

        // Format into OpenAI response
        let finalContent = puterResponse;
        if (Array.isArray(puterResponse.message?.content)) {
            finalContent = puterResponse.message.content
                .filter(c => c.type === 'text')
                .map(c => c.text)
                .join('\n');
        } else if (puterResponse.message?.content) {
            finalContent = puterResponse.message.content;
        }

        const openAIResponse = {
            id: `chatcmpl-${Date.now()}`,
            object: "chat.completion",
            created: Math.floor(Date.now() / 1000),
            model: model || 'claude-sonnet-4',
            choices: [
                {
                    index: 0,
                    message: {
                        role: "assistant",
                        content: finalContent
                    },
                    finish_reason: "stop"
                }
            ],
            usage: {
                prompt_tokens: 0,
                completion_tokens: 0,
                total_tokens: 0
            }
        };

        res.json(openAIResponse);
    } catch (error) {
        console.error("[PROXY ERROR]", error);
        res.status(500).json({
            error: {
                message: error.message || "Unknown error during Puter call",
                stack: error.stack,
                type: "puter_error"
            }
        });
    }
});

app.listen(port, () => {
    console.log(`🚀 Puter-to-OpenAI Proxy running on http://localhost:${port}`);
    console.log(`👉 Point your CLAUDE_PROXY_URL to http://localhost:${port}/v1`);
});
