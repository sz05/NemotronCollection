I want to work on the following system components. The goal is to build a platform where users interact with an AI while completing specific tasks, with the system continuously evaluating the quality and relevance of their interaction and awarding additional points for verified task completion.

## 1. Model Validation

First, confirm which models should be used for each component of the system.

In particular, we need to benchmark a few **small, efficient embedding models** for semantic matching. The embedding model should be lightweight enough to run within the **AWS Lambda free-tier/resource constraints**, so we should avoid unnecessarily large embedding models.

For each candidate model, evaluate:

- Semantic matching accuracy
- Precision / recall
- False-positive and false-negative rates
- Latency
- Memory requirements
- Embedding generation cost
- Suitability for deployment in AWS Lambda

The objective is to select the smallest/most efficient model that provides sufficiently reliable semantic matching.

---

## 2. Semantic Matching / Relevance Guardrail

We need a semantic relevance-checking system that prevents users from taking the conversation substantially off-topic.

The system should maintain a **compact summary of the current conversation context** rather than continuously embedding the entire conversation.

For every new user query:

1. Maintain/update a summary representing the current conversational context.
2. Compare the new user query semantically against:
   - The current conversation summary/context
   - The user's original task

3. Generate cosine similarity scores using the selected embedding model.
4. Define an appropriate threshold for determining whether the query is sufficiently relevant.

The initial threshold to test is:

**Cosine similarity < 0.15 → potentially off-topic**

If the query falls below the threshold, do **not immediately reject it**. Instead, show the user a warning such as:

> "This doesn't seem closely related to your current task or conversation. Are you sure you want to continue?"

Provide two options:

- **Yes, continue** → send the query to the LLM normally.
- **No, go back** → allow the user to revise the query.

The threshold of **0.15 should be benchmarked rather than blindly assumed to be correct**. We need to determine the threshold that provides the best tradeoff between catching genuinely irrelevant queries and avoiding false warnings for legitimate conversational transitions.

The benchmark should allow us to determine:

- Which embedding model performs best
- The optimal cosine-similarity threshold
- Precision/recall at different thresholds
- False-warning rate
- Rate of genuinely off-topic queries detected
- Performance across different task types

---

## 3. Sliding-Window Context

When the conversation is sent to Gemini, we should **not send the entire conversation indefinitely**.

Instead, create a local context consisting of:

1. **Original task / theme**
2. **Current conversation summary**
3. The previous **4–5 user responses**
4. The previous **4–5 LLM responses**

This creates a sliding-window context that is sent to Gemini.

The purpose of this local context is primarily to allow the scoring system to understand the user's recent interaction while keeping the context small and predictable.

We need to benchmark:

- Whether 4–5 turns are sufficient
- Whether more or fewer turns improve scoring
- How much information is lost when older messages leave the window
- Whether the summary adequately preserves important information
- The impact of context size on Gemini's scoring consistency
- Token usage and latency

---

## 4. Conversation Scoring

Each conversation should receive a **live score** based on the quality of the user's interaction.

The scoring criteria are:

### A. Responsiveness — 30%

**Does the participant engage with what the AI says?**

Measure whether the user actually responds to and engages with the AI's previous response rather than producing disconnected or generic responses.

### B. Elaboration — 25%

**Does the participant provide meaningful explanations/details?**

Measure the depth, specificity, reasoning, examples, and useful details provided by the participant.

### C. Development — 25%

**Does the conversation evolve and build on previous information?**

Measure whether the participant builds upon earlier discussion, introduces useful developments, and maintains continuity rather than repeatedly restarting or repeating the same points.

### D. Progress — 20%

**Is the participant making reasonable progress toward a substantive session?**

Measure whether the conversation is moving toward meaningful completion/development of the task rather than remaining superficial or stagnant.

The overall live score should be:

**LiveScore = 0.30R + 0.25E + 0.25D + 0.20P**

The scoring model should receive only the required context:

- Original task/theme
- Current conversation summary
- Recent 4–5 user messages
- Recent 4–5 LLM messages

We should benchmark whether this limited context is sufficient for reliable scoring.

---

## 5. Task Completion Scoring

In addition to the live conversation score, users should receive **additional points when they actually complete their assigned task**.

Task completion points should only be awarded after the submitted **proof of completion has been verified**.

The system should distinguish between:

- Conversation quality score
- Task completion score
- Proof verification confidence

A user should not receive task-completion points merely because they claim to have completed the task.

We should determine:

- How many points each task should provide
- Whether task difficulty should affect the points
- Whether completion quality should affect the points
- How verified completion should interact with the live conversation score
- How to prevent users from gaming the scoring system

---

## 6. Proof of Completion

Build a reliable mechanism for users to submit evidence that they completed their assigned task.

The system should determine:

- What constitutes valid proof
- What evidence users can submit
- How the evidence is verified
- What can be automatically verified
- What requires human verification
- How fabricated or manipulated evidence can be detected
- How duplicate/reused evidence can be detected

The key principle is:

**Points for task completion are awarded only after successful verification.**

The proof system should be designed so that simply uploading something that looks convincing is not sufficient.

---

## 7. Anti-Fraud / Proof-of-Completion Guardrail

We need a clear and professional warning explaining that users must submit **genuine proof of completion**.

The warning should make three things explicit:

1. Proof must represent work actually completed by the participant.
2. Fabricated, manipulated, misleading, or falsely submitted evidence is not allowed.
3. Attempting to fake completion may result in **disqualification from the platform/benchmark and removal of associated points**.

The warning should be presented before users submit proof, rather than only after fraud is detected.

We should also investigate technical mechanisms for detecting:

- Edited screenshots
- Fake/generated evidence
- Reused evidence
- Evidence belonging to another task/user
- Evidence generated without actually completing the task
- Attempts to manipulate verification

The goal is to create a strong deterrent without making the platform unnecessarily hostile to legitimate users.
