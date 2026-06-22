const puter = require('@heyputer/puter.js').puter;
require('dotenv').config();

const PUTER_TOKEN = process.env.PUTER_TOKEN;
puter.setAuthToken(PUTER_TOKEN);

console.log("Checking available models...");
const modelId = 'gpt-4o-mini';
console.log(`Trying model: ${modelId}`);
puter.ai.chat([{role: 'user', content: 'hi'}], {model: modelId})
    .then(res => console.log("Success with model! Response:", res))
    .catch(err => console.log("Failed:", err.message || err));
