/**
 * Minimal LangGraph example: give a ReAct agent a real human to ask.
 *
 * Prereqs: npm i @pushary/langgraph @langchain/langgraph @langchain/core @langchain/openai
 * Run:     PUSHARY_API_KEY=... OPENAI_API_KEY=... npx tsx examples/basic.ts
 */
import { ChatOpenAI } from '@langchain/openai'
import { createReactAgent } from '@langchain/langgraph/prebuilt'
import { connect, createAskHumanTool } from '@pushary/langgraph'

const config = { apiKey: process.env.PUSHARY_API_KEY! }
const userId = 'user_123'

async function main() {
  // 1) One time per end-user: connect their phone.
  const { universalLink } = await connect(config, userId)
  console.log('Ask the user to open:', universalLink)

  // 2) Give the agent a tool that blocks on a real human, fail-closed.
  const askHuman = createAskHumanTool(config, { externalId: userId })
  const agent = createReactAgent({
    llm: new ChatOpenAI({ model: 'gpt-4o' }),
    tools: [askHuman],
  })

  const res = await agent.invoke({
    messages: [{ role: 'user', content: 'Issue a $40 refund, but only if a human approves.' }],
  })
  console.log(res.messages.at(-1)?.content)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
