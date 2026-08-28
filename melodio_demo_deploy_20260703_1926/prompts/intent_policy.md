# Melodio Intent Policy

This document is the source of truth for intent labeling. Prompt changes and eval labels should follow this policy instead of adding one-off rules.

## Priority

When a query can match multiple intents, use the user's final task:

1. Function/control if the user is operating playback, queue, playlist, library, rating, sharing, downloading, settings, or current playback status.
2. Creation/editing if the user asks the system to make, write, generate, edit, transform, mix, or process audio/lyrics.
3. Entity search if the user wants to find or play a specific existing song, artist, album, playlist, or lyric-matched song.
4. Content recommendation if the user wants existing songs by mood, scene, style, language, similarity, or broad taste.
5. Music QA if the user asks for facts, background, explanation, or appreciation.
6. Chitchat/fallback if there is no clear music/product task.

## Confirmed Boundaries

### 1. Existing Songs vs Creation

- "来一首/放一首/推荐一首" means listening to existing songs.
- "播放/放/听/推荐 + song/style/scene/mood" is content recommendation or entity search, not creation.
- "做/写/创作/生成/整一首" means creation, unless the query clearly asks to play or recommend existing songs.

### 2. State Statements

- Mood, weather, life status, and casual statements do not trigger recommendation by themselves.
- If there is no explicit music action such as "想听/推荐/播放/适合听/来几首/配乐", classify as chitchat.
- With explicit listening action, classify as filtered recommendation.

### 3. Current Playback Queries

- Current playback status queries are function/control: "这首歌叫什么", "现在这首歌叫啥", "还有多久播完".
- Explanation/background questions are music QA: "这首歌是谁唱的", "给我介绍下现在放的这首歌", "赏析一下这首歌".

### 4. Similar Artist

- Similar artist requests are content recommendation/similar recommendation when the product returns playable songs.
- Only classify as music QA if the user explicitly asks for an informational artist list/explanation without playback/recommendation output.

### 5. Implicit Feedback

- Praise/complaints/reactions count as implicit feedback only when there is playback or recommendation context.
- Without playback context, short reactions are chitchat.

### 6. Context-Dependent Short Queries

- "再来一首/换一个风格/有没有类似的" must use conversation context.
- With playback/recommendation context, classify based on the referenced current song/list.
- Without context, degrade to general recommendation or fallback depending on whether the query implies listening to music.

### 7. Lyric Fragment Search

- Lyric fragments used to identify a song are entity search.
- Examples: "那首歌词里有...的歌叫什么", "为何旧知己 在最后 变不到老友".

### 8. Product Operations

- Favorite, add to playlist, comment, share, rate, download, follow, queue, playlist editing all map to function/control at the product label level.
- Do not expose fine-grained favorite/comment/share labels in the eval L2; map them to operation instruction.
