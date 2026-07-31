# Safe-to-touch traffic lights

Classify the files and areas a reader might want to edit into four buckets. The
point is to tell a nervous owner where they can experiment and where they'll
break production. Be specific: name files or directories, not vague categories.

### ✅ Green: safe to modify freely
Copy, styling, static content, README text, isolated UI components, config values
with obvious effects. Editing these can't take the system down.

### ⚠️ Yellow: modify with care
Business logic, forms, routes, and components with a few dependents. A mistake is
recoverable but will visibly break a feature. Read the file fully first.

### 🔶 Orange: needs context before touching
Shared state, data models, auth flows, API contracts, anything several other files
import. Changing these has ripple effects the editor must trace first.

### 🚫 Red: do not modify without a full review
Payment handling, webhook verification, security/crypto, migration scripts,
secrets management, deployment entry points. A blind edit here loses money, leaks
data, or takes the whole app down.

## How to assign a file

- Count who imports/depends on it → more dependents pushes it toward orange/red.
- Judge blast radius if it's wrong → money, data, or downtime = red.
- Reversibility → easily reverted = greener; irreversible (migrations, payments) = redder.

When unsure, round **up** in severity. Warning a user off a safe file costs a
little friction; waving them onto a dangerous one costs an outage.
