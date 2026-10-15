# A remote agent over SSH

The agent (Claude Code, Codex, etc.) runs on **another computer**, the panel runs on a server. The panel is not opened to the network.

1. On the server open **Agent connections** → register the agent → the **Remote connection → SSH** block. If the SSH server is off, the panel says how to turn it on (on a Mac: "Remote Login").
2. Pick the agent. On the agent's computer run the shown `ssh-keygen` command — a separate key just for this agent.
3. Paste the contents of the `.pub` file into the field and press **Build the line**. Add the resulting line as ONE line to `~/.ssh/authorized_keys` on the server. The panel does not edit that file itself.
4. On the agent's computer run the shown `claude mcp add …` command (or paste the JSON into the client's settings).

The key can **only** start the MCP bridge of this agent: no shell, no port forwarding, the agent's secret never leaves the server. The agent's rights (L1/L2/L3) and the approval of changes stay on the server, as with local use.

Revoking: delete the line from `authorized_keys` or revoke the agent on the page.
