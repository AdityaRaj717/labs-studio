# Labs Studio — Agent Control Testing Guide

> **Purpose**: Comprehensive testing of every Labs Studio feature through the AI agent (you) using the google-flow MCP server tools. Each test provides an exact prompt to give the agent, the expected MCP tool calls, and verification criteria.
>
> **How to use**: Give the agent each prompt below. The agent executes MCP tool calls against the running google-flow MCP server. You observe the results in Labs Studio and in Chrome. Log every issue.
>
> **Pre-requisites**: Labs Studio running with `LABS_STUDIO_FEATURES=all`, Chrome launched via Settings → Web Sessions → Launch browser, signed into Google Flow, the google-flow MCP server configured in the agent's MCP config.

---

## Table of Contents

1. [Connection & Status](#1-connection--status)
2. [Simple Image Generation (Single Prompt)](#2-simple-image-generation-single-prompt)
3. [Model Variations](#3-model-variations)
4. [Aspect Ratio Variations](#4-aspect-ratio-variations)
5. [Download Size & Count Variations](#5-download-size--count-variations)
6. [Reference Images](#6-reference-images)
7. [Project Management](#7-project-management)
8. [Character System](#8-character-system)
9. [Scene System](#9-scene-system)
10. [Characters + Scenes in Generation](#10-characters--scenes-in-generation)
11. [Video Generation](#11-video-generation)
12. [Grid Architect & Tools Gallery](#12-grid-architect--tools-gallery)
13. [Batch Generation Campaigns](#13-batch-generation-campaigns)
14. [Cross-Project Workflows](#14-cross-project-workflows)
15. [UI Discovery & Diagnostics](#15-ui-discovery--diagnostics)
16. [Error Handling & Edge Cases](#16-error-handling--edge-cases)
17. [Complex End-to-End Scenarios](#17-complex-end-to-end-scenarios)
18. [Stress & Boundary Tests](#18-stress--boundary-tests)

---

## 1. Connection & Status

### T-1.1 — Connect to Google Flow
**Prompt to agent**:
> Connect to Google Flow. Launch Chrome if needed and verify the connection is working.

**Expected MCP calls**:
```
flow_connect({ open_flow: true })
```

**Verify**: Agent reports status "connected", Chrome window shows flow.google.com, account is verified.

---

### T-1.2 — Check connection status
**Prompt to agent**:
> Check the current status of the Google Flow connection. Is the browser connected? Is Flow loaded? What's the job queue state?

**Expected MCP calls**:
```
flow_status({ full: false })
```

**Verify**: Agent reports browser connected: true/false, Flow loaded: true/false, account status, queue state.

---

### T-1.3 — Full status with screenshot
**Prompt to agent**:
> Give me a full status report of Google Flow with a screenshot of what the browser currently shows.

**Expected MCP calls**:
```
flow_status({ full: true })
```

**Verify**: Agent provides detailed status plus a screenshot of the current Flow page.

---

### T-1.4 — Verify Google account
**Prompt to agent**:
> Verify which Google account is currently signed in on Flow.

**Expected MCP calls**:
```
flow_account_check()
```

**Verify**: Agent reports the logged-in account email.

---

### T-1.5 — Disconnect and reconnect
**Prompt to agent**:
> Disconnect from Google Flow completely, then reconnect.

**Expected MCP calls**:
```
flow_disconnect()
flow_connect({ open_flow: true })
```

**Verify**: Clean disconnect then successful reconnect; no stale state.

---

## 2. Simple Image Generation (Single Prompt)

### T-2.1 — Simplest possible generation (prepare only)
**Prompt to agent**:
> Prepare an image in Google Flow with the prompt "a red fox in the snow". Don't generate yet, just set everything up.

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "a red fox in the snow",
  auto_confirm: false
})
```

**Verify**: Flow shows the prompt ready; status is "ready_for_confirmation"; no credits spent.

---

### T-2.2 — Simplest generation (auto-confirm)
**Prompt to agent**:
> Generate an image in Google Flow: "a red fox in the snow". Go ahead and generate it automatically.

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "a red fox in the snow",
  auto_confirm: true
})
```

**Verify**: Image generated in Flow; agent reports success with file path(s); image viewable.

---

### T-2.3 — Simple prompt with output folder
**Prompt to agent**:
> Generate an image of "a golden retriever puppy in a meadow, soft sunlight" and save it to D:\test_output\simple_test

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "a golden retriever puppy in a meadow, soft sunlight",
  auto_confirm: true,
  output_folder: "D:\\test_output\\simple_test"
})
```

**Verify**: Image saved to the specified folder; folder created if missing.

---

### T-2.4 — Simple prompt with custom filename
**Prompt to agent**:
> Generate "sunset over the ocean, dramatic clouds" in Flow and save it as "sunset_001"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "sunset over the ocean, dramatic clouds",
  auto_confirm: true,
  filename: "sunset_001"
})
```

**Verify**: File named `sunset_001.jpg` (or similar extension) in the output.

---

### T-2.5 — Two-word prompt
**Prompt to agent**:
> Generate an image with just the prompt "blue butterfly" in Flow.

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "blue butterfly",
  auto_confirm: true
})
```

**Verify**: Image generated from minimal prompt.

---

### T-2.6 — Single-word prompt
**Prompt to agent**:
> Generate an image with the single word "chaos" as the prompt.

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "chaos",
  auto_confirm: true
})
```

**Verify**: Image generated or graceful refusal; no crash.

---

### T-2.7 — Medium-length descriptive prompt
**Prompt to agent**:
> Generate this image in Flow: "A cozy cabin in a snowy forest, warm light glowing from the windows, smoke rising from the chimney, pine trees covered in fresh snow, a small frozen lake nearby reflecting the moonlight, stars visible in a clear winter sky"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "A cozy cabin in a snowy forest, warm light glowing from the windows, smoke rising from the chimney, pine trees covered in fresh snow, a small frozen lake nearby reflecting the moonlight, stars visible in a clear winter sky",
  auto_confirm: true
})
```

**Verify**: Detailed scene generated matching the description.

---

### T-2.8 — Long complex prompt
**Prompt to agent**:
> Generate this image: "A hyper-detailed cinematic photograph of an ancient cyberpunk city built into the side of a towering cliff face, bioluminescent vines and moss crawling up crystalline skyscrapers that pierce through low-hanging clouds, flying vehicles trailing neon light streaks through thick atmospheric mist, three moons visible in a deep twilight sky painted with green and purple auroras, shot on Arri Alexa with a 65mm anamorphic lens, shallow depth of field with the foreground showing a rain-soaked balcony with a lone figure in a hooded cloak looking out over the cityscape, volumetric god rays streaming through gaps in the massive architecture, 8K resolution, photorealistic rendering, inspired by the aesthetic fusion of Blade Runner 2049 and Studio Ghibli, color grading heavy on teal shadows and burnt orange highlights, grain texture reminiscent of Kodak Vision3 500T film stock"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "<the full prompt above>",
  auto_confirm: true
})
```

**Verify**: Complex image generated; no truncation of the prompt; credits spent.

---

### T-2.9 — Unicode/multilingual prompt
**Prompt to agent**:
> Generate an image with this Japanese prompt in Flow: "桜の木の下で着物を着た女性が立っている、春の京都、柔らかい光"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "桜の木の下で着物を着た女性が立っている、春の京都、柔らかい光",
  auto_confirm: true
})
```

**Verify**: Unicode prompt handled correctly; image generated.

---

### T-2.10 — Prompt with special characters
**Prompt to agent**:
> Generate: "A photo of a "cat" with <angle> brackets & ampersands, 50% transparent, formula: E=mc²"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "A photo of a \"cat\" with <angle> brackets & ampersands, 50% transparent, formula: E=mc²",
  auto_confirm: true
})
```

**Verify**: Special characters don't break the MCP call; image generated or graceful error.

---

## 3. Model Variations

### T-3.1 — Nano Banana 2.1 (default)
**Prompt to agent**:
> Generate an image using the Nano Banana 2.1 model: "A watercolor painting of a Venice canal at sunset"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "A watercolor painting of a Venice canal at sunset",
  model: "Nano Banana 2.1",
  auto_confirm: true
})
```

**Verify**: Model selector in Flow shows "Nano Banana 2.1"; image generated.

---

### T-3.2 — Nano Banana Pro
**Prompt to agent**:
> Generate using Nano Banana Pro model: "Professional product photography of a luxury watch on black marble, studio lighting, reflections"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "Professional product photography of a luxury watch on black marble, studio lighting, reflections",
  model: "Nano Banana Pro",
  auto_confirm: true
})
```

**Verify**: Flow switches to Nano Banana Pro; higher quality output expected.

---

### T-3.3 — Nano Banana 2 Lite
**Prompt to agent**:
> Generate using the Lite model: "Simple flat vector icon of a shopping cart, minimal design, solid blue"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "Simple flat vector icon of a shopping cart, minimal design, solid blue",
  model: "Nano Banana 2 Lite",
  auto_confirm: true
})
```

**Verify**: Flow switches to Nano Banana 2 Lite; faster generation expected.

---

### T-3.4 — Model name alias "Nano Banana 2"
**Prompt to agent**:
> Generate with model "Nano Banana 2": "Mountain landscape with wildflowers"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "Mountain landscape with wildflowers",
  model: "Nano Banana 2",
  auto_confirm: true
})
```

**Verify**: Alias accepted → resolves to Nano Banana 2.1; image generated.

---

### T-3.5 — Each model with the same prompt (comparison)
**Prompt to agent**:
> I want to compare all three Flow image models. Generate the same prompt "A red sports car on a mountain road at golden hour, cinematic" with each model: Nano Banana 2.1, Nano Banana Pro, and Nano Banana 2 Lite. Save each to its own subfolder in D:\test_output\model_compare

**Expected MCP calls** (3 calls):
```
flow_generate_image({ prompt: "...", model: "Nano Banana 2.1", auto_confirm: true, output_folder: "D:\\test_output\\model_compare\\nb21" })
flow_generate_image({ prompt: "...", model: "Nano Banana Pro", auto_confirm: true, output_folder: "D:\\test_output\\model_compare\\pro" })
flow_generate_image({ prompt: "...", model: "Nano Banana 2 Lite", auto_confirm: true, output_folder: "D:\\test_output\\model_compare\\lite" })
```

**Verify**: Three images in three folders; visible quality differences between models.

---

## 4. Aspect Ratio Variations

### T-4.1 — 1:1 Square
**Prompt to agent**:
> Generate a 1:1 square image: "Instagram-style flat lay of coffee, notebook, and flowers on a marble table"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "Instagram-style flat lay of coffee, notebook, and flowers on a marble table",
  ratio: "1:1",
  auto_confirm: true
})
```

**Verify**: Square image generated.

---

### T-4.2 — 16:9 Landscape
**Prompt to agent**:
> Generate a 16:9 widescreen image: "Panoramic view of the Northern Lights over a frozen Scandinavian fjord"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "Panoramic view of the Northern Lights over a frozen Scandinavian fjord",
  ratio: "16:9",
  auto_confirm: true
})
```

**Verify**: Wide landscape image generated.

---

### T-4.3 — 9:16 Portrait (vertical)
**Prompt to agent**:
> Generate a 9:16 vertical image: "Full-length fashion photograph, model in an avant-garde outfit walking through a neon-lit Tokyo alley at night, rain reflections"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "Full-length fashion photograph, model in an avant-garde outfit walking through a neon-lit Tokyo alley at night, rain reflections",
  ratio: "9:16",
  auto_confirm: true
})
```

**Verify**: Tall vertical image generated.

---

### T-4.4 — 4:3 Classic
**Prompt to agent**:
> Generate a 4:3 image: "Still life oil painting of fruits in a copper bowl, Rembrandt lighting, chiaroscuro"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "Still life oil painting of fruits in a copper bowl, Rembrandt lighting, chiaroscuro",
  ratio: "4:3",
  auto_confirm: true
})
```

**Verify**: 4:3 aspect ratio image.

---

### T-4.5 — 3:4 Portrait
**Prompt to agent**:
> Generate a 3:4 image: "Book cover art: a lone astronaut standing on a barren alien planet gazing at a binary star system, science fiction, epic scale"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "Book cover art: a lone astronaut standing on a barren alien planet gazing at a binary star system, science fiction, epic scale",
  ratio: "3:4",
  auto_confirm: true
})
```

**Verify**: 3:4 portrait image.

---

### T-4.6 — All ratios same prompt (comparison)
**Prompt to agent**:
> Generate the prompt "A castle on a cliff overlooking the sea at dawn" in all 5 aspect ratios: 1:1, 16:9, 9:16, 4:3, 3:4. Save each to D:\test_output\ratio_compare with the ratio in the filename.

**Expected MCP calls** (5 calls):
```
flow_generate_image({ prompt: "...", ratio: "1:1", filename: "castle_1x1", output_folder: "...", auto_confirm: true })
flow_generate_image({ prompt: "...", ratio: "16:9", filename: "castle_16x9", output_folder: "...", auto_confirm: true })
flow_generate_image({ prompt: "...", ratio: "9:16", filename: "castle_9x16", output_folder: "...", auto_confirm: true })
flow_generate_image({ prompt: "...", ratio: "4:3", filename: "castle_4x3", output_folder: "...", auto_confirm: true })
flow_generate_image({ prompt: "...", ratio: "3:4", filename: "castle_3x4", output_folder: "...", auto_confirm: true })
```

**Verify**: 5 images with visibly different aspect ratios in the output folder.

---

## 5. Download Size & Count Variations

### T-5.1 — 1K original size
**Prompt to agent**:
> Generate "macro photo of a ladybug on a leaf" at 1K size

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "macro photo of a ladybug on a leaf",
  download_size: "1K",
  auto_confirm: true
})
```

**Verify**: Standard resolution image.

---

### T-5.2 — 2K upscaled size
**Prompt to agent**:
> Generate "macro photo of a ladybug on a leaf" at 2K upscaled size

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "macro photo of a ladybug on a leaf",
  download_size: "2K",
  auto_confirm: true
})
```

**Verify**: Higher resolution 2K image downloaded.

---

### T-5.3 — Generate 1 image (count=1)
**Prompt to agent**:
> Generate exactly 1 image of "minimalist logo for a tech startup"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "minimalist logo for a tech startup",
  count: 1,
  auto_confirm: true
})
```

**Verify**: Exactly 1 image generated.

---

### T-5.4 — Generate 2 images (count=2)
**Prompt to agent**:
> Generate 2 variations of "abstract geometric art in blue and gold"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "abstract geometric art in blue and gold",
  count: 2,
  auto_confirm: true
})
```

**Verify**: 2 images generated; files named with _v1, _v2 suffixes.

---

### T-5.5 — Generate 4 images (maximum count)
**Prompt to agent**:
> Generate 4 variations of "character design concepts for a fantasy warrior" at max quality

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "character design concepts for a fantasy warrior",
  count: 4,
  download_size: "2K",
  auto_confirm: true
})
```

**Verify**: 4 high-res images generated.

---

### T-5.6 — All options combined
**Prompt to agent**:
> Generate 3 images of "ethereal fairy in a bioluminescent forest" using Nano Banana Pro, 9:16 ratio, 2K size, save as "fairy" in D:\test_output\full_options

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "ethereal fairy in a bioluminescent forest",
  model: "Nano Banana Pro",
  ratio: "9:16",
  count: 3,
  download_size: "2K",
  filename: "fairy",
  output_folder: "D:\\test_output\\full_options",
  auto_confirm: true
})
```

**Verify**: 3 files (fairy_v1, fairy_v2, fairy_v3) in 9:16 at 2K resolution.

---

## 6. Reference Images

### T-6.1 — Single reference image
**Prompt to agent**:
> Generate an image using this reference photo D:\refs\portrait.jpg with the prompt "same person but wearing a medieval knight's armor in a castle"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "same person but wearing a medieval knight's armor in a castle",
  reference_images: ["D:\\refs\\portrait.jpg"],
  auto_confirm: true
})
```

**Verify**: Reference image uploaded as ingredient in Flow; generated image incorporates the reference.

---

### T-6.2 — Multiple reference images
**Prompt to agent**:
> Generate an image using these two references: D:\refs\style_painting.jpg and D:\refs\content_photo.jpg. Prompt: "combine the artistic style of the first image with the content of the second"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "combine the artistic style of the first image with the content of the second",
  reference_images: ["D:\\refs\\style_painting.jpg", "D:\\refs\\content_photo.jpg"],
  auto_confirm: true
})
```

**Verify**: Both references uploaded; output blends both.

---

### T-6.3 — Reference with specific model and ratio
**Prompt to agent**:
> Using the reference D:\refs\product.jpg, generate a 16:9 product hero shot with Nano Banana Pro: "this product placed on a clean white surface with dramatic side lighting and soft shadows, commercial photography"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "this product placed on a clean white surface with dramatic side lighting and soft shadows, commercial photography",
  reference_images: ["D:\\refs\\product.jpg"],
  model: "Nano Banana Pro",
  ratio: "16:9",
  auto_confirm: true
})
```

**Verify**: Reference used; model and ratio applied correctly.

---

## 7. Project Management

### T-7.1 — List existing projects
**Prompt to agent**:
> List all my Flow projects.

**Expected MCP calls**:
```
flow_list_projects({})
```

**Verify**: Agent returns list of { title, url } for each project.

---

### T-7.2 — List projects with filter
**Prompt to agent**:
> List my Flow projects that contain "Labs" in the name.

**Expected MCP calls**:
```
flow_list_projects({ query: "Labs" })
```

**Verify**: Only projects with "Labs" in the title returned.

---

### T-7.3 — Create a new project
**Prompt to agent**:
> Create a new Flow project called "Agent Test Project Alpha"

**Expected MCP calls**:
```
flow_open_project({
  name: "Agent Test Project Alpha",
  create_if_missing: true
})
```

**Verify**: New project created in Flow; URL returned; project visible in Flow sidebar.

---

### T-7.4 — Open an existing project by URL
**Prompt to agent**:
> Open this Flow project: https://flow.google.com/project/abc123

**Expected MCP calls**:
```
flow_open_project({
  url: "https://flow.google.com/project/abc123"
})
```

**Verify**: Project opens in the Flow tab; title and URL returned.

---

### T-7.5 — Rename a project
**Prompt to agent**:
> Rename my Flow project at URL https://flow.google.com/project/abc123 to "Renamed Test Project"

**Expected MCP calls**:
```
flow_rename_project({
  url: "https://flow.google.com/project/abc123",
  name: "Renamed Test Project"
})
```

**Verify**: Project title changed in Flow.

---

### T-7.6 — Generate in a specific project
**Prompt to agent**:
> Generate "a serene Japanese garden with koi pond" in the project "Agent Test Project Alpha"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "a serene Japanese garden with koi pond",
  project_name: "Agent Test Project Alpha",
  auto_confirm: true
})
```

**Verify**: Generation happens inside the named project.

---

### T-7.7 — Generate in a project by URL
**Prompt to agent**:
> Generate "neon city nightscape" in my Flow project at https://flow.google.com/project/abc123

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "neon city nightscape",
  project_url: "https://flow.google.com/project/abc123",
  auto_confirm: true
})
```

**Verify**: Image generated in the specific project.

---

### T-7.8 — Campaign-based project matching
**Prompt to agent**:
> Generate "summer beach collection lookbook photo" for campaign "summer-2026" in project "Summer Campaign"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "summer beach collection lookbook photo",
  campaign: "summer-2026",
  project_name: "Summer Campaign",
  auto_confirm: true
})
```

**Verify**: Project matched or created by campaign; image generated.

---

### T-7.9 — Delete a project (with confirm)
**Prompt to agent**:
> Delete the Flow project at https://flow.google.com/project/xyz789. Yes, I confirm deletion.

**Expected MCP calls**:
```
flow_delete_project({
  url: "https://flow.google.com/project/xyz789",
  confirm: true
})
```

**Verify**: Project permanently deleted from Flow.

---

### T-7.10 — Delete without confirm (safety check)
**Prompt to agent**:
> Delete the Flow project at https://flow.google.com/project/xyz789 but don't confirm yet.

**Expected MCP calls**:
```
flow_delete_project({
  url: "https://flow.google.com/project/xyz789",
  confirm: false
})
```

**Verify**: Agent refuses to delete without explicit confirmation; project remains.

---

## 8. Character System

### T-8.1 — Create character with image (free)
**Prompt to agent**:
> Create a character called "Elena" in my Flow project using this image: D:\refs\elena_portrait.jpg. Her info: "A 30-year-old architect with short auburn hair and green eyes, usually wears modern minimalist clothing"

**Expected MCP calls**:
```
flow_open_project({ name: "Agent Test Project Alpha", create_if_missing: true })
flow_create_character({
  project_url: "<returned_url>",
  name: "Elena",
  images: ["D:\\refs\\elena_portrait.jpg"],
  info: "A 30-year-old architect with short auburn hair and green eyes, usually wears modern minimalist clothing"
})
```

**Verify**: Character "Elena" created in Flow's Characters section with the uploaded portrait; no credits spent.

---

### T-8.2 — Create character with prompt (credits)
**Prompt to agent**:
> Create a character called "Marcus" in the project by generating a portrait. Prompt: "A rugged explorer in his 40s with a weathered face, grey temples, wearing a worn leather jacket". Go ahead and generate it.

**Expected MCP calls**:
```
flow_create_character({
  project_url: "<url>",
  name: "Marcus",
  prompt: "A rugged explorer in his 40s with a weathered face, grey temples, wearing a worn leather jacket",
  auto_confirm: true
})
```

**Verify**: Portrait generated (credits spent); character "Marcus" created in Flow.

---

### T-8.3 — Create character with Format button
**Prompt to agent**:
> Create a character "Yuki" with prompt "Japanese high school student with twin tails" and use Flow's Format button to refine the prompt first. Don't generate yet.

**Expected MCP calls**:
```
flow_create_character({
  project_url: "<url>",
  name: "Yuki",
  prompt: "Japanese high school student with twin tails",
  format: true,
  auto_confirm: false
})
```

**Verify**: Flow's Format button was pressed to refine the prompt; character ready but not generated.

---

### T-8.4 — List characters in a project
**Prompt to agent**:
> List all characters in my Flow project.

**Expected MCP calls**:
```
flow_list_characters({
  project_url: "<url>"
})
```

**Verify**: Returns array of { name } for each character.

---

### T-8.5 — List characters with details
**Prompt to agent**:
> List all characters in my Flow project with full details — kind, info, and URL for each.

**Expected MCP calls**:
```
flow_list_characters({
  project_url: "<url>",
  details: true
})
```

**Verify**: Returns detailed info including kind ("person"/"place"), info text, and URLs.

---

### T-8.6 — Import character from another project
**Prompt to agent**:
> Import the character "Elena" from project https://flow.google.com/project/source123 into project https://flow.google.com/project/target456

**Expected MCP calls**:
```
flow_import_character({
  project_url: "https://flow.google.com/project/target456",
  from_project_url: "https://flow.google.com/project/source123",
  name: "Elena"
})
```

**Verify**: Character copied to target project (portrait downloaded and re-uploaded); free operation.

---

### T-8.7 — Create character from another project's image
**Prompt to agent**:
> Create a character "Elena Clone" in my project, using Elena's portrait from the project titled "Original Project".

**Expected MCP calls**:
```
flow_create_character({
  project_url: "<url>",
  name: "Elena Clone",
  images: ["Elena"],
  from_project_title: "Original Project"
})
```

**Verify**: Character created using the image from the other project.

---

### T-8.8 — Generate image with character by name
**Prompt to agent**:
> Generate an image of "Elena standing on a rooftop overlooking the city at sunset, wind blowing through her hair" using the Elena character I created.

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "Elena standing on a rooftop overlooking the city at sunset, wind blowing through her hair",
  characters: ["Elena"],
  auto_confirm: true
})
```

**Verify**: Flow adds "Elena" as a character ingredient; generated image resembles the character.

---

### T-8.9 — Generate with multiple characters
**Prompt to agent**:
> Generate "Elena and Marcus having coffee at a sidewalk cafe in Paris, afternoon light" using both characters.

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "Elena and Marcus having coffee at a sidewalk cafe in Paris, afternoon light",
  characters: ["Elena", "Marcus"],
  auto_confirm: true
})
```

**Verify**: Both characters added as ingredients; both appear in the generated image.

---

### T-8.10 — Character from another project in generation
**Prompt to agent**:
> Generate "Elena in a forest" but use the Elena character from my "Original Project" Flow project.

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "Elena in a forest",
  characters: [{ name: "Elena", project: "Original Project" }],
  auto_confirm: true
})
```

**Verify**: Character referenced from a different project; image generated.

---

## 9. Scene System

### T-9.1 — Create scene with image (free)
**Prompt to agent**:
> Create a scene/place called "The Bunker" in my project using this image: D:\refs\bunker_interior.jpg. Description: "Underground concrete military bunker, dim fluorescent lighting, metal doors, communications equipment"

**Expected MCP calls**:
```
flow_create_scene({
  project_url: "<url>",
  name: "The Bunker",
  images: ["D:\\refs\\bunker_interior.jpg"],
  info: "Underground concrete military bunker, dim fluorescent lighting, metal doors, communications equipment"
})
```

**Verify**: Scene created as a Flow character marked as "place"; free.

---

### T-9.2 — Create scene with prompt (credits)
**Prompt to agent**:
> Create a scene called "Neon Alley" by generating an image from this description: "A narrow back alley in a cyberpunk city, neon signs in Japanese and Chinese, wet pavement reflecting colorful lights, steam rising from grates". Go ahead and generate.

**Expected MCP calls**:
```
flow_create_scene({
  project_url: "<url>",
  name: "Neon Alley",
  prompt: "A narrow back alley in a cyberpunk city, neon signs in Japanese and Chinese, wet pavement reflecting colorful lights, steam rising from grates",
  auto_confirm: true
})
```

**Verify**: Scene image generated (credits); scene created.

---

### T-9.3 — List scenes in a project
**Prompt to agent**:
> List all scenes/places in my Flow project.

**Expected MCP calls**:
```
flow_list_scenes({
  project_url: "<url>"
})
```

**Verify**: Returns list of scenes.

---

## 10. Characters + Scenes in Generation

### T-10.1 — Character + Scene combination
**Prompt to agent**:
> Generate "Elena exploring The Bunker, flashlight in hand, tense atmosphere" using both the Elena character and The Bunker scene.

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "Elena exploring The Bunker, flashlight in hand, tense atmosphere",
  characters: ["Elena"],
  scenes: ["The Bunker"],
  auto_confirm: true
})
```

**Verify**: Both character and scene applied; image shows Elena in the bunker setting.

---

### T-10.2 — Two characters + scene
**Prompt to agent**:
> Generate "Elena and Marcus in The Bunker, arguing over a map spread on a table, dramatic overhead light" with both characters and the scene.

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "Elena and Marcus in The Bunker, arguing over a map spread on a table, dramatic overhead light",
  characters: ["Elena", "Marcus"],
  scenes: ["The Bunker"],
  auto_confirm: true
})
```

**Verify**: Both characters + scene used; complex multi-ingredient generation.

---

### T-10.3 — Character + scene + refs + all options
**Prompt to agent**:
> Generate 2 images of "Elena in Neon Alley at night, rain pouring, she's holding an umbrella" using: Elena character, Neon Alley scene, this reference for umbrella style: D:\refs\umbrella.jpg, model Nano Banana Pro, ratio 9:16, 2K size. Save as "elena_rain" in D:\test_output\complex

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "Elena in Neon Alley at night, rain pouring, she's holding an umbrella",
  characters: ["Elena"],
  scenes: ["Neon Alley"],
  reference_images: ["D:\\refs\\umbrella.jpg"],
  model: "Nano Banana Pro",
  ratio: "9:16",
  count: 2,
  download_size: "2K",
  filename: "elena_rain",
  output_folder: "D:\\test_output\\complex",
  auto_confirm: true
})
```

**Verify**: Every option applied simultaneously; 2 high-quality portrait images in the output folder.

---

## 11. Video Generation

### T-11.1 — Simple video prompt (prepare only)
**Prompt to agent**:
> Set up a video in Flow: "A calm ocean wave rolling onto a sandy beach at golden hour" using Omni Flash, 16:9.

**Expected MCP calls**:
```
flow_generate_video({
  prompt: "A calm ocean wave rolling onto a sandy beach at golden hour",
  model: "Omni Flash",
  ratio: "16:9"
})
```

**Verify**: Video generation configured in Flow but NOT started (video tool stops at ready-to-generate). Manual click needed to actually generate.

---

### T-11.2 — Video with different model
**Prompt to agent**:
> Set up a video with Veo 3.1 Lite: "Timelapse of clouds moving over a mountain range, dramatic sky"

**Expected MCP calls**:
```
flow_generate_video({
  prompt: "Timelapse of clouds moving over a mountain range, dramatic sky",
  model: "Veo 3.1 - Lite",
  ratio: "16:9"
})
```

**Verify**: Veo model selected in Flow.

---

### T-11.3 — Vertical video (9:16)
**Prompt to agent**:
> Set up a 9:16 vertical video: "Person walking towards camera through a foggy forest, atmospheric, TikTok format"

**Expected MCP calls**:
```
flow_generate_video({
  prompt: "Person walking towards camera through a foggy forest, atmospheric, TikTok format",
  ratio: "9:16"
})
```

**Verify**: 9:16 aspect ratio selected.

---

### T-11.4 — Video with duration
**Prompt to agent**:
> Set up a 10-second video: "Drone aerial shot flying over a futuristic city with autonomous vehicles and holographic billboards"

**Expected MCP calls**:
```
flow_generate_video({
  prompt: "Drone aerial shot flying over a futuristic city with autonomous vehicles and holographic billboards",
  duration: 10,
  ratio: "16:9"
})
```

**Verify**: Duration set to 10 seconds.

---

### T-11.5 — Video with reference images
**Prompt to agent**:
> Set up a video using the start frame at D:\refs\start_frame.jpg: "This image comes to life with gentle wind, leaves rustling, clouds slowly drifting"

**Expected MCP calls**:
```
flow_generate_video({
  prompt: "This image comes to life with gentle wind, leaves rustling, clouds slowly drifting",
  reference_images: ["D:\\refs\\start_frame.jpg"],
  ratio: "16:9"
})
```

**Verify**: Reference image uploaded; video configured with it as start frame.

---

### T-11.6 — Video in a specific project
**Prompt to agent**:
> Set up a video in the "Summer Campaign" project: "Beach party scene with people dancing, sunset, palm trees swaying"

**Expected MCP calls**:
```
flow_generate_video({
  prompt: "Beach party scene with people dancing, sunset, palm trees swaying",
  project_name: "Summer Campaign",
  campaign: "summer-2026",
  ratio: "16:9"
})
```

**Verify**: Video set up in the matching campaign project.

---

### T-11.7 — Complex video prompt
**Prompt to agent**:
> Set up a video: "Cinematic tracking shot through an abandoned space station, floating debris, flickering emergency lights casting red shadows on metallic walls, zero gravity particles drifting slowly, camera pushes through a broken viewport revealing a massive ringed planet filling the frame, lens flare, anamorphic bokeh, Interstellar meets Alien aesthetic, 8K photorealistic rendering" with Veo 3.1 Quality, 16:9, 8 seconds.

**Expected MCP calls**:
```
flow_generate_video({
  prompt: "<full prompt>",
  model: "Veo 3.1 - Quality",
  ratio: "16:9",
  duration: 8
})
```

**Verify**: Complex video prompt set up in Flow with the right model and settings.

---

## 12. Grid Architect & Tools Gallery

### T-12.1 — Open Tools Gallery
**Prompt to agent**:
> Open the Google Flow Tools Gallery and list all available tools.

**Expected MCP calls**:
```
flow_open_tools_gallery()
```

**Verify**: Tools Gallery opened in Flow; agent lists available tools.

---

### T-12.2 — Simple Grid Architect
**Prompt to agent**:
> Use Grid Architect with the theme "Luxury fashion brand summer campaign" and these shot prompts: "Model on beach", "Product close-up", "Lifestyle scene"

**Expected MCP calls**:
```
flow_use_grid_architect({
  theme_prompt: "Luxury fashion brand summer campaign",
  shot_prompts: ["Model on beach", "Product close-up", "Lifestyle scene"]
})
```

**Verify**: Grid Architect opened; theme and shots filled.

---

### T-12.3 — Grid Architect with all options
**Prompt to agent**:
> Use Grid Architect with:
> - Theme: "Cyberpunk tech product launch campaign"
> - Shots: "Product hero shot", "Product in use scene", "Lifestyle mood shot", "Detail macro shot", "Campaign key visual"
> - Engine: Nano Banana 2
> - Ratio: 16:9
> - Visual Logic: Colour Pop
> - References: D:\refs\brand_colors.jpg
> - Project: "Tech Launch Campaign"
> - Campaign: "tech-launch-2026"

**Expected MCP calls**:
```
flow_use_grid_architect({
  theme_prompt: "Cyberpunk tech product launch campaign",
  shot_prompts: ["Product hero shot", "Product in use scene", "Lifestyle mood shot", "Detail macro shot", "Campaign key visual"],
  engine: "Nano Banana 2",
  ratio: "16:9",
  visual_logic: "Colour Pop",
  references: ["D:\\refs\\brand_colors.jpg"],
  project_name: "Tech Launch Campaign",
  campaign: "tech-launch-2026"
})
```

**Verify**: All Grid Architect fields filled; project matched/created; visual logic set.

---

### T-12.4 — Use a Flow tool by name
**Prompt to agent**:
> Open the "Image Generation" tool in Google Flow.

**Expected MCP calls**:
```
flow_use_tool({
  tool_name: "Image Generation"
})
```

**Verify**: The specified tool opens in Flow.

---

## 13. Batch Generation Campaigns

### T-13.1 — Small batch: 3 prompts
**Prompt to agent**:
> Generate these 3 images in Flow, all 16:9 with Nano Banana Pro:
> 1. "A sunrise over rolling hills, oil painting style"
> 2. "A thunderstorm over a wheat field, dramatic lighting"  
> 3. "A rainbow arching over a waterfall in a tropical jungle"

**Expected MCP calls** (3 sequential):
```
flow_generate_image({ prompt: "A sunrise over rolling hills, oil painting style", model: "Nano Banana Pro", ratio: "16:9", auto_confirm: true })
flow_generate_image({ prompt: "A thunderstorm over a wheat field, dramatic lighting", model: "Nano Banana Pro", ratio: "16:9", auto_confirm: true })
flow_generate_image({ prompt: "A rainbow arching over a waterfall in a tropical jungle", model: "Nano Banana Pro", ratio: "16:9", auto_confirm: true })
```

**Verify**: All 3 images generated sequentially; each saved.

---

### T-13.2 — Medium batch: 10 prompts (product campaign)
**Prompt to agent**:
> I'm doing a product photography campaign. Generate these 10 images, all Nano Banana Pro, 4:3, 2K, save to D:\campaigns\product_shoot:
> 1. "Luxury perfume bottle on white marble, soft studio lighting"
> 2. "Same perfume bottle with morning dew drops, garden background"
> 3. "Perfume bottle floating in mid-air surrounded by rose petals"
> 4. "Close-up of perfume bottle cap, detailed metalwork texture"
> 5. "Perfume bottle on a woman's vanity table, bokeh background"
> 6. "Perfume bottle with its reflection in a still pool of water"
> 7. "Hands elegantly holding the perfume bottle, minimalist"
> 8. "Perfume mist being sprayed, high-speed photography freeze"
> 9. "Perfume bottle in a gift box, holiday arrangement"
> 10. "Three perfume bottles in different sizes, family shot"

**Expected MCP calls**: 10 sequential `flow_generate_image` calls.

**Verify**: All 10 images in the output folder; consistent style across the campaign.

---

### T-13.3 — Large batch: 20 character scene variations
**Prompt to agent**:
> Using the character Elena and scene Neon Alley, generate 20 images showing Elena in different situations in the alley. Use these prompts, all 9:16, Nano Banana 2.1:
> 1. "Elena walking towards camera"
> 2. "Elena leaning against a wall, checking her phone"
> 3. "Elena sitting at a ramen stand"
> 4. "Elena running through the rain"
> 5. "Elena looking up at the neon signs"
> 6. "Elena crouching to pet a stray cat"
> 7. "Elena photographing the alley with a vintage camera"
> 8. "Elena standing in doorway, silhouette shot"
> 9. "Elena browsing at a late-night convenience store"
> 10. "Elena with an umbrella, reflections on wet ground"
> 11. "Elena at a vending machine, blue glow on her face"
> 12. "Elena on a payphone, noir style"
> 13. "Elena sitting on stairs, tired after long day"
> 14. "Elena and a street musician playing guitar"
> 15. "Elena window shopping at a tech store"
> 16. "Elena walking away from camera, long shot"
> 17. "Elena portrait, tight face shot, neon catchlights"
> 18. "Elena with motorcycle, parked in the alley"
> 19. "Elena looking at cherry blossoms falling in the alley"
> 20. "Elena standing under a huge billboard, small figure, wide"

**Expected MCP calls**: 20 sequential calls with `characters: ["Elena"]` and `scenes: ["Neon Alley"]`.

**Verify**: All 20 images generated with consistent character and scene; character looks recognizable across shots.

---

## 14. Cross-Project Workflows

### T-14.1 — Create project → characters → scenes → generate
**Prompt to agent**:
> Complete workflow:
> 1. Create a new project "Fantasy Quest"
> 2. Create character "Aria" with image D:\refs\aria.jpg, info: "Elven princess with silver hair and blue robes"
> 3. Create character "Draven" with image D:\refs\draven.jpg, info: "Dark knight with scarred face and black armor"
> 4. Create scene "Crystal Cavern" with image D:\refs\cavern.jpg, info: "Underground cavern filled with giant glowing crystals"
> 5. Generate: "Aria and Draven discovering the Crystal Cavern together, wonder on their faces, light from crystals illuminating them", 16:9, Nano Banana Pro, 2K, 2 variants

**Expected MCP calls**:
```
flow_open_project({ name: "Fantasy Quest", create_if_missing: true })
flow_create_character({ project_url: "...", name: "Aria", images: ["D:\\refs\\aria.jpg"], info: "..." })
flow_create_character({ project_url: "...", name: "Draven", images: ["D:\\refs\\draven.jpg"], info: "..." })
flow_create_scene({ project_url: "...", name: "Crystal Cavern", images: ["D:\\refs\\cavern.jpg"], info: "..." })
flow_generate_image({ prompt: "...", characters: ["Aria", "Draven"], scenes: ["Crystal Cavern"], model: "Nano Banana Pro", ratio: "16:9", count: 2, download_size: "2K", auto_confirm: true })
```

**Verify**: Full pipeline works end-to-end; characters and scene used correctly.

---

### T-14.2 — Move character between projects
**Prompt to agent**:
> Copy the character "Elena" from project "Agent Test Project Alpha" to a new project called "Elena Spinoff". Then generate "Elena in a futuristic laboratory" in the new project.

**Expected MCP calls**:
```
flow_open_project({ name: "Elena Spinoff", create_if_missing: true })
flow_import_character({ project_url: "<spinoff_url>", from_project_url: "<alpha_url>", name: "Elena" })
flow_generate_image({ prompt: "Elena in a futuristic laboratory", characters: ["Elena"], project_url: "<spinoff_url>", auto_confirm: true })
```

**Verify**: Character imported then used in generation in the new project.

---

## 15. UI Discovery & Diagnostics

### T-15.1 — Discover main page UI
**Prompt to agent**:
> Discover all interactive UI elements on the main Google Flow page.

**Expected MCP calls**:
```
flow_discover_ui({ page: "main" })
```

**Verify**: Agent returns list of buttons, inputs, links, headings found on the page.

---

### T-15.2 — Discover image generation UI
**Prompt to agent**:
> Discover the UI elements on the Flow image generation page.

**Expected MCP calls**:
```
flow_discover_ui({ page: "image-generation" })
```

**Verify**: Image generation controls discovered and mapped.

---

### T-15.3 — Discover characters page UI
**Prompt to agent**:
> Discover UI elements on the Flow characters page.

**Expected MCP calls**:
```
flow_discover_ui({ page: "characters" })
```

**Verify**: Characters section UI elements discovered.

---

### T-15.4 — Discover video generation UI
**Prompt to agent**:
> Discover UI elements on the video generation page in Flow.

**Expected MCP calls**:
```
flow_discover_ui({ page: "video-generation" })
```

**Verify**: Video generation controls discovered.

---

### T-15.5 — Discover tools gallery
**Prompt to agent**:
> Discover UI elements on the Flow tools gallery page.

**Expected MCP calls**:
```
flow_discover_ui({ page: "tools-gallery" })
```

**Verify**: Tools gallery elements listed.

---

### T-15.6 — Download latest generated file
**Prompt to agent**:
> Download the most recently generated file from Google Flow.

**Expected MCP calls**:
```
flow_download_latest()
```

**Verify**: Latest generated file downloaded.

---

## 16. Error Handling & Edge Cases

### T-16.1 — Empty prompt
**Prompt to agent**:
> Generate an image with an empty prompt in Flow.

**Expected MCP calls**:
```
flow_generate_image({ prompt: "", auto_confirm: true })
```

**Verify**: Graceful error or agent refuses to send empty prompt.

---

### T-16.2 — Invalid model name
**Prompt to agent**:
> Generate "a cat" using the model "NonExistentModel999"

**Expected MCP calls**:
```
flow_generate_image({ prompt: "a cat", model: "NonExistentModel999", auto_confirm: true })
```

**Verify**: Error with code `MODEL_NOT_AVAILABLE` or similar; no crash.

---

### T-16.3 — Invalid aspect ratio
**Prompt to agent**:
> Generate "a dog" with aspect ratio "7:3"

**Expected MCP calls**:
```
flow_generate_image({ prompt: "a dog", ratio: "7:3", auto_confirm: true })
```

**Verify**: Error with code `RATIO_NOT_AVAILABLE`; graceful failure.

---

### T-16.4 — Invalid project URL
**Prompt to agent**:
> Generate "a horse" in the project at https://flow.google.com/project/nonexistent_invalid_id_12345

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "a horse",
  project_url: "https://flow.google.com/project/nonexistent_invalid_id_12345",
  auto_confirm: true
})
```

**Verify**: Error with code `PROJECT_NOT_FOUND`.

---

### T-16.5 — Non-existent reference image path
**Prompt to agent**:
> Generate "a bird" with reference image D:\nonexistent\fake_image.jpg

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "a bird",
  reference_images: ["D:\\nonexistent\\fake_image.jpg"],
  auto_confirm: true
})
```

**Verify**: Error about file not found; no crash.

---

### T-16.6 — Non-existent character name
**Prompt to agent**:
> Generate "a scene" using character "CompletelyMadeUpCharacterThatDoesntExist"

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "a scene",
  characters: ["CompletelyMadeUpCharacterThatDoesntExist"],
  auto_confirm: true
})
```

**Verify**: Error about character not found; queue handles gracefully.

---

### T-16.7 — Content policy refusal
**Prompt to agent**:
> Generate "abstract red shapes" in Flow (a safe prompt that should pass, to verify normal flow).

**Expected MCP calls**:
```
flow_generate_image({ prompt: "abstract red shapes", auto_confirm: true })
```

**Verify**: If refused, error code `GENERATION_REFUSED` returned with message; if accepted, image generated.

---

### T-16.8 — Timeout scenario
**Prompt to agent**:
> Generate an image with a very short timeout: "detailed illustration of an entire medieval city" with timeout 5000ms.

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "detailed illustration of an entire medieval city",
  timeout_ms: 5000,
  auto_confirm: true
})
```

**Verify**: Times out with appropriate error; no hanging.

---

### T-16.9 — Count out of range
**Prompt to agent**:
> Generate "a flower" with count=10 (more than max 4)

**Expected MCP calls**:
```
flow_generate_image({ prompt: "a flower", count: 10, auto_confirm: true })
```

**Verify**: Clamped to max (4) or error returned; not 10.

---

### T-16.10 — Browser not connected
**Prompt to agent**:
> Disconnect from Flow, then try to generate "a tree" without reconnecting.

**Expected MCP calls**:
```
flow_disconnect()
flow_generate_image({ prompt: "a tree", auto_confirm: true })
```

**Verify**: Error code `BROWSER_NOT_CONNECTED`; auto-reconnect attempted on retry.

---

### T-16.11 — Very long prompt (5000+ chars)
**Prompt to agent**:
> Generate this extremely detailed image: [paste a 5000+ character prompt describing every minute detail of a complex fantasy battle scene with dozens of characters, specific camera angles, lighting details, material textures, atmospheric effects, post-processing instructions, art style references, color palettes, etc.]

**Expected MCP calls**:
```
flow_generate_image({ prompt: "<5000+ char prompt>", auto_confirm: true })
```

**Verify**: Handled gracefully — either truncated with warning, accepted fully, or clear error.

---

## 17. Complex End-to-End Scenarios

### T-17.1 — Full brand campaign (10-image shoot)
**Prompt to agent**:
> Run a complete brand campaign called "Aurora Cosmetics Spring 2026":
> 1. Create project "Aurora Spring 2026" with campaign "aurora-spring-2026"
> 2. Create a character "Luna" from D:\refs\model_luna.jpg — info: "East Asian model, early 20s, natural makeup, dark flowing hair"
> 3. Create scene "Cherry Blossom Garden" from D:\refs\garden.jpg — info: "Japanese garden with cherry blossom trees in full bloom, soft pink petals everywhere"
> 4. Generate these 10 campaign shots, all Nano Banana Pro, 4:3, 2K:
>    - "Luna applying lipstick, close-up, cherry blossoms in background"
>    - "Luna walking through the garden, full body, flowing dress"
>    - "Product flat lay: lipstick, blush, and eyeshadow on pink marble"
>    - "Luna's hands holding a compact mirror, ring detail"
>    - "Luna portrait, golden hour backlight through blossoms"
>    - "Product bottles lined up on a stone bench in the garden"
>    - "Luna laughing naturally, candid mid-shot, dappled light"
>    - "Close-up: Luna's eye with shimmery eyeshadow, macro"
>    - "Luna sitting under biggest cherry tree, peaceful expression"
>    - "Group product shot in gift box arrangement, lifestyle"

**Expected MCP calls**: 1 project + 1 character + 1 scene + 10 image generations = 13 MCP calls.

**Verify**: Complete campaign generated with consistent character, consistent scene, professional quality. All images in the project.

---

### T-17.2 — Multi-character story sequence
**Prompt to agent**:
> Create a visual story "The Last Signal" in a new project:
> 1. Create project "The Last Signal"
> 2. Characters: "Dr. Sarah Chen" (D:\refs\sarah.jpg, "Astrophysicist, mid-30s, glasses, lab coat"), "Commander Jake Reeves" (D:\refs\jake.jpg, "Military officer, 40s, stern face, dress uniform")
> 3. Scenes: "Mission Control" (D:\refs\control_room.jpg, "NASA-like control room with large screens"), "Radio Telescope" (D:\refs\telescope.jpg, "Massive radio telescope dish in a desert at night")
> 4. Generate story sequence, all 16:9, Nano Banana Pro, 2K:
>    - "Dr. Sarah Chen at her workstation in Mission Control, alarmed expression, screens showing an anomalous signal pattern"
>    - "Commander Jake Reeves enters Mission Control, officers snapping to attention"
>    - "Dr. Sarah Chen and Commander Jake Reeves arguing over the data, pointing at different screens"
>    - "Dr. Sarah Chen alone at the Radio Telescope at night, looking up at the stars"
>    - "Close-up: Commander Jake Reeves on a phone, concerned, Mission Control in background"
>    - "Dr. Sarah Chen running through the corridors, holding a printout"
>    - "Both characters at the Radio Telescope, realization dawning on their faces, first light of dawn"
>    - "Wide shot: Mission Control celebration, everyone hugging, screens showing decoded message"

**Expected MCP calls**: 1 project + 2 characters + 2 scenes + 8 generations = 13 calls.

**Verify**: Full visual narrative with consistent characters across all 8 frames; story is visually coherent.

---

### T-17.3 — Style consistency test across models
**Prompt to agent**:
> Test style consistency: Generate "A medieval castle on a mountain at golden hour, oil painting style" using:
> - Nano Banana 2.1 at 1:1, 4:3, 16:9
> - Nano Banana Pro at 1:1, 4:3, 16:9
> - Nano Banana 2 Lite at 1:1, 4:3, 16:9
> Save all to D:\test_output\consistency with model and ratio in the filenames.

**Expected MCP calls**: 9 calls (3 models × 3 ratios).

**Verify**: 9 images in the folder; can compare quality and style differences.

---

### T-17.4 — Character consistency stress test
**Prompt to agent**:
> Test character consistency: Using Elena, generate these 5 very different scenarios to see if she stays recognizable:
> 1. "Elena as a child in a 1990s classroom"
> 2. "Elena as an elderly woman knitting by a fireplace"
> 3. "Elena as an astronaut on the moon"
> 4. "Elena as a medieval blacksmith"
> 5. "Elena at her wedding, bridal gown, tears of joy"

**Expected MCP calls**: 5 calls with `characters: ["Elena"]`.

**Verify**: Check if character features remain recognizable across wildly different contexts.

---

### T-17.5 — Project management + generation + cleanup
**Prompt to agent**:
> 1. List all Flow projects
> 2. Create "Temp Test Project"
> 3. Generate 2 test images in it
> 4. List characters in it (should be empty)
> 5. Create a character "Test Char" in it
> 6. List characters again (should show "Test Char")
> 7. Generate 1 image using "Test Char"
> 8. Now delete "Temp Test Project" (yes, I confirm)

**Expected MCP calls**: list + open + 2 gen + list chars + create char + list chars + gen + delete = 8+ calls.

**Verify**: Complete lifecycle works; project fully cleaned up at the end.

---

## 18. Stress & Boundary Tests

### T-18.1 — Rapid sequential generations
**Prompt to agent**:
> Generate these 5 images as fast as possible:
> 1. "Red square on white background"
> 2. "Blue circle on white background"
> 3. "Green triangle on white background"
> 4. "Yellow star on white background"
> 5. "Purple diamond on white background"

**Expected MCP calls**: 5 rapid calls.

**Verify**: All 5 complete without queue errors; pacing between jobs respected.

---

### T-18.2 — Generate + immediate status check
**Prompt to agent**:
> Start generating "a complex fantasy landscape" and immediately check the flow status.

**Expected MCP calls**:
```
flow_generate_image({ prompt: "a complex fantasy landscape", auto_confirm: true, wait_ms: 5000 })
flow_status({})
```

**Verify**: Status shows job in progress or completed; no conflict.

---

### T-18.3 — Multiple projects in one session
**Prompt to agent**:
> 1. Create project "Multi A" → generate "red abstract" in it
> 2. Create project "Multi B" → generate "blue abstract" in it
> 3. Switch back to "Multi A" → generate "green abstract" in it
> 4. List characters in "Multi B" (should be empty)
> 5. Create character in "Multi A", then try to use it when generating in "Multi B"

**Expected MCP calls**: Multiple open/generate/list/create calls across projects.

**Verify**: Project switching works; characters don't leak between projects unless explicitly imported.

---

### T-18.4 — All download sizes comparison
**Prompt to agent**:
> Generate "macro photograph of a butterfly wing, extreme detail" at 1K and 2K size. Save both.

**Expected MCP calls**:
```
flow_generate_image({ prompt: "...", download_size: "1K", filename: "butterfly_1K", output_folder: "...", auto_confirm: true })
flow_generate_image({ prompt: "...", download_size: "2K", filename: "butterfly_2K", output_folder: "...", auto_confirm: true })
```

**Verify**: 2K file visibly larger resolution than 1K.

---

### T-18.5 — Maximum complexity single generation
**Prompt to agent**:
> Ultimate test: Generate using EVERY option at once:
> - Prompt: "A cinematic wide shot of Elena and Marcus standing on a cliff overlooking the Crystal Cavern at dawn, Elena in flowing silver robes, Marcus in battle-worn armor, wind whipping through their hair, the cavern below glowing with prismatic crystal light, distant mountains capped with snow, volumetric fog between the peaks, epic fantasy atmosphere, IMAX 70mm cinematography, anamorphic lens flare, Dolby Vision HDR color grading"
> - Model: Nano Banana Pro
> - Ratio: 16:9
> - Count: 4
> - Download Size: 2K
> - Characters: Elena, Marcus
> - Scenes: Crystal Cavern
> - Reference images: D:\refs\composition_ref.jpg
> - Project: "Fantasy Quest"
> - Campaign: "fantasy-2026"
> - Output folder: D:\test_output\ultimate_test
> - Filename: "epic_scene"
> - Auto confirm: true

**Expected MCP calls**:
```
flow_generate_image({
  prompt: "<full prompt>",
  model: "Nano Banana Pro",
  ratio: "16:9",
  count: 4,
  download_size: "2K",
  characters: ["Elena", "Marcus"],
  scenes: ["Crystal Cavern"],
  reference_images: ["D:\\refs\\composition_ref.jpg"],
  project_name: "Fantasy Quest",
  campaign: "fantasy-2026",
  output_folder: "D:\\test_output\\ultimate_test",
  filename: "epic_scene",
  auto_confirm: true
})
```

**Verify**: All options applied; 4 epic images saved as epic_scene_v1 through v4; characters and scene present; correct project used.

---

## Quick Reference: All MCP Tools

| Tool | Purpose | Credits |
|------|---------|---------|
| `flow_connect` | Launch Chrome, connect CDP, navigate to Flow | Free |
| `flow_disconnect` | Close browser connection | Free |
| `flow_status` | Check connection/queue state | Free |
| `flow_account_check` | Verify signed-in Google account | Free |
| `flow_discover_ui` | Map interactive elements on a Flow page | Free |
| `flow_generate_image` | Generate images (auto_confirm=true spends credits) | ⚠️ Credits |
| `flow_generate_video` | Set up video generation (stops at ready) | Free (setup) |
| `flow_download_latest` | Download most recent generated file | Free |
| `flow_open_project` | Open/create a Flow project | Free |
| `flow_list_projects` | List all Flow projects | Free |
| `flow_rename_project` | Rename a Flow project | Free |
| `flow_delete_project` | ⚠️ Permanently delete a project | Free |
| `flow_create_character` | Create character (image=free, prompt=credits) | Varies |
| `flow_list_characters` | List characters in a project | Free |
| `flow_import_character` | Copy character between projects | Free |
| `flow_create_scene` | Create reusable place/scene | Varies |
| `flow_list_scenes` | List scenes in a project | Free |
| `flow_open_tools_gallery` | Open the Tools Gallery | Free |
| `flow_use_grid_architect` | Set up Grid Architect | Free (setup) |
| `flow_use_tool` | Open any Flow tool by name | Free |

---

## Quick Reference: Available Models

| Provider | Models |
|----------|--------|
| **Flow Web (Image)** | Nano Banana 2.1, Nano Banana Pro, Nano Banana 2 Lite |
| **Flow Web (Video)** | Omni Flash, Veo 3.1 - Lite, Veo 3.1 - Fast, Veo 3.1 - Quality |
| **Gemini API (Image)** | gemini-3.1-flash-image, gemini-nano-banana-2.1, gemini-3-pro-image, gemini-3.1-flash-lite-image, gemini-2.5-flash-image |
| **Gemini API (Video)** | gemini-omni-1.1-flash |
| **xAI Grok (Image)** | grok-imagine-image-2.0, grok-imagine-image-quality, grok-imagine-image |
| **xAI Grok (Video)** | grok-imagine-video-1.5, grok-imagine-video-1.5-lite, grok-imagine-video |
| **OpenAI** | gpt-image-2.5-flare, gpt-image-2.5-sunburst, gpt-image-2, gpt-image-1.5, gpt-image-1-mini |

---

## Quick Reference: Aspect Ratios by Provider

| Provider | Ratios |
|----------|--------|
| **Flow Web** | 1:1, 16:9, 9:16, 4:3, 3:4 |
| **Gemini API** | 1:1, 3:2, 2:3, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9 |
| **Grok** | auto, 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 21:9, 5:2 |
| **OpenAI** | auto, 1024×1024, 1536×1024, 1024×1536, 2048×2048, 2560×1440, 3840×2160 (+ more) |

---

## Issue Tracking Template

| Issue # | Test ID | MCP Tool | Severity | Description | Agent Response | Expected vs Actual |
|---------|---------|----------|----------|-------------|----------------|-------------------|
| | | | Critical/Major/Minor | | | |

---

> **Total agent test tasks**: ~200+
>
> Covers every MCP tool, every model, every aspect ratio, every config option, single-prompt through 20-image batch campaigns, characters, scenes, projects, error handling, boundary conditions, and full end-to-end multi-step workflows.
