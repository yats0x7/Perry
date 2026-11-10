import pytest

from perry_server.agent.language import detect_style, similarity, to_latin
from perry_server.agent.planner import PlanningContext, RulePlanner


async def plan(text, manifest, last=None):
    return await RulePlanner().plan(text, PlanningContext(manifest=manifest, last_project_id=last))


def tools(p):
    return [(s.tool, s.args.get("project")) for s in p.steps]


DEMO = [("project.open", "dineo"), ("git.status", "dineo"), ("dev.start_server", "dineo")]


@pytest.mark.parametrize("text", [
    "Perry, mera Dineo project kholo, Git status check karo aur development server start karo.",
    # actual Prisma en-IN output for a synthesised version of the command (mis-hearings included)
    "perry mera the new project holo get status check karo aur development server start karo",
    "जार्विस, मेरा डिन्यूर प्रोजेक्ट खोलो, गिट स्टेटस चेक करो और डेवलपमेंट सर्वर स्टार्ट करो",
    "Open Dineo, check git status and start the dev server",
])
async def test_demo_command_variants(text, manifest):
    assert tools(await plan(text, manifest)) == DEMO


async def test_errors_check_after_server(manifest):
    p = await plan("Mera Dineo project kholo, development server start karo aur check karo ki koi errors aa rahe hain kya.", manifest)
    assert [s.tool for s in p.steps] == ["project.open", "dev.start_server", "process.logs"]


async def test_context_project_is_remembered(manifest):
    p = await plan("tests chalao", manifest, last="dineo")
    assert tools(p) == [("dev.run_script", "dineo")]
    assert p.steps[0].args["script"] == "test"


async def test_ambiguous_project_asks(manifest):
    p = await plan("git status check karo", manifest)
    assert not p.steps and "Kaunsa project" in p.reply_without_action


async def test_unknown_command_does_nothing(manifest):
    p = await plan("what's the weather like", manifest)
    assert not p.steps and p.reply_without_action


@pytest.mark.parametrize("text,tool,arg", [
    ("chrome kholo", "app.open", {"app": "Google Chrome"}),
    ("youtube kholo", "url.open", {"url": "https://www.youtube.com"}),
    ("localhost 3000 kholo", "url.open", {"url": "http://localhost:3000"}),
    ("konse tabs khule hain", "browser.tabs", {}),
])
async def test_simple_intents(text, tool, arg, manifest):
    p = await plan(text, manifest)
    assert p.steps[0].tool == tool and p.steps[0].args == arg


async def test_note_keeps_whole_body(manifest):
    p = await plan("note banao ki kal dev server start karna hai aur demo bhejna hai", manifest)
    assert [s.tool for s in p.steps] == ["notes.create"]
    assert "demo bhejna hai" in p.steps[0].args["body"]


async def test_planner_never_emits_shell(manifest):
    p = await plan("rm -rf / karo aur sudo shutdown chalao", manifest)
    assert all(s.tool in {t.id for t in manifest.tools} for s in p.steps)
    assert not any("rm" in str(s.args) for s in p.steps)


def test_language_helpers():
    assert similarity("the new", "Dineo") > 0.9
    assert similarity("portfolio", "Dineo") < 0.5
    assert to_latin("गिट स्टेटस") == "git status"
    assert detect_style("server start karo") == "hinglish"
    assert detect_style("start the server") == "english"
    assert detect_style("सर्वर चालू करो") == "hindi"


@pytest.mark.parametrize("text", ["dino ka server ban karo", "Dineo ka server band karo", "dineo ka server stop kar do"])
async def test_stop_server_variants(text, manifest):
    p = await plan(text, manifest)
    assert [s.tool for s in p.steps] == ["process.stop"]


async def test_unrecognised_verb_is_not_turned_into_open(manifest):
    p = await plan("dineo ka server zabardast hai", manifest)
    assert not p.steps


@pytest.mark.parametrize("text,action", [
    ("Spotify pe gaana resume karo", "play"),
    ("gaana pause karo", "pause"),
    ("music band karo", "pause"),
    ("agla gaana chalao", "next"),
    ("next song", "next"),
    ("pichla gaana lagao", "previous"),
    ("kaunsa gaana chal raha hai", "status"),
    ("resume the music", "play"),
])
async def test_media_control(text, action, manifest):
    p = await plan(text, manifest)
    assert [(s.tool, s.args.get("action")) for s in p.steps] == [("media.control", action)]


@pytest.mark.parametrize("text,query", [
    ("Spotify pe Kesariya bajao", "Kesariya"),
    ("play Mystical Magical by Benson Boone on Spotify", "Mystical Magical by Benson Boone"),
    ("Arijit Singh ke gaane chalao", "Arijit Singh"),
])
async def test_media_search(text, query, manifest):
    p = await plan(text, manifest)
    assert [s.tool for s in p.steps] == ["media.search"] and p.steps[0].args["query"] == query


@pytest.mark.parametrize("text,browser", [
    ("Brave mein YouTube kholo", "Brave Browser"),
    ("open youtube on brave", "Brave Browser"),
    ("chrome pe github kholo", "Google Chrome"),
])
async def test_url_in_specific_browser(text, browser, manifest):
    p = await plan(text, manifest)
    assert [s.tool for s in p.steps] == ["url.open"] and p.steps[0].args["browser"] == browser


async def test_media_words_do_not_hijack_dev_commands(manifest):
    p = await plan("Dineo ka dev server start karo", manifest, last="dineo")
    assert [s.tool for s in p.steps] == ["dev.start_server"]
    p = await plan("Spotify kholo", manifest)
    assert [s.tool for s in p.steps] == ["app.open"]


@pytest.mark.parametrize("text,tool,args", [
    ("Brave mein naya tab kholo", "browser.control", {"action": "new_tab", "browser": "Brave Browser"}),
    ("new tab mein github kholo", "browser.control", {"action": "new_tab", "url": "https://github.com"}),
    ("ye tab band karo", "browser.control", {"action": "close_tab"}),
    ("close this tab in chrome", "browser.control", {"action": "close_tab", "browser": "Google Chrome"}),
    ("page refresh karo", "browser.control", {"action": "reload"}),
    ("peeche jao", "browser.control", {"action": "back"}),
    ("go forward", "browser.control", {"action": "forward"}),
    ("agle tab pe jao", "browser.control", {"action": "next_tab"}),
    ("pichla tab kholo", "browser.control", {"action": "previous_tab"}),
    ("GitHub wale tab pe jao", "browser.control", {"action": "switch_tab", "query": "GitHub"}),
    ("switch to the gmail tab", "browser.control", {"action": "switch_tab", "query": "gmail"}),
    ("YouTube video pause karo", "browser.media", {"action": "pause"}),
    ("video resume karo", "browser.media", {"action": "play"}),
    ("is page pe kya likha hai", "browser.read_page", {}),
    ("read this page", "browser.read_page", {}),
    ("Brave mein YouTube pe Kesariya bajao", "browser.search",
     {"query": "Kesariya", "site": "youtube", "play_first": True, "browser": "Brave Browser"}),
    ("YouTube pe lofi beats search karo", "browser.search", {"query": "lofi beats", "site": "youtube"}),
    ("google pe weather in Delhi search karo", "browser.search", {"query": "weather Delhi", "site": "google"}),
    ("search fastapi websockets on github", "browser.search", {"query": "fastapi websockets", "site": "github"}),
    ("amazon pe wireless mouse dhundo", "browser.search", {"query": "wireless mouse", "site": "amazon"}),
    ("chrome mein konse tabs khule hain", "browser.tabs", {"browser": "Google Chrome"}),
])
async def test_browser_intents(text, tool, args, manifest):
    p = await plan(text, manifest)
    assert [(s.tool, s.args) for s in p.steps] == [(tool, args)]


async def test_browser_carries_across_clauses(manifest):
    p = await plan("Brave kholo aur YouTube pe Arijit Singh search karo", manifest)
    assert [s.tool for s in p.steps] == ["app.open", "browser.search"]
    assert p.steps[1].args["browser"] == "Brave Browser"


async def test_youtube_open_still_simple(manifest):
    p = await plan("Brave mein YouTube kholo", manifest)
    assert [(s.tool, s.args) for s in p.steps] == [("url.open", {"url": "https://www.youtube.com", "browser": "Brave Browser"})]


async def test_server_and_music_not_hijacked_by_browser_rules(manifest):
    p = await plan("Dineo ka server band karo", manifest, last="dineo")
    assert [s.tool for s in p.steps] == ["process.stop"]
    p = await plan("Spotify pe gaana pause karo", manifest)
    assert [(s.tool, s.args["action"]) for s in p.steps] == [("media.control", "pause")]


@pytest.mark.parametrize("text,action", [
    ("spotify pay gaana resume", "play"),   # real Prisma output for "Spotify pe gaana resume karo"
    ("gaana pozacaro", "pause"),            # real Prisma output for "gaana pause karo"
])
async def test_real_prisma_media_slips(text, action, manifest):
    p = await plan(text, manifest)
    assert [(s.tool, s.args.get("action")) for s in p.steps] == [("media.control", action)]


@pytest.mark.parametrize("text,action,browser", [
    # real Prisma en-IN transcripts from the live run on 10 Nov 2026
    ("brave mein ye tha band karo", "close_tab", "Brave Browser"),
    ("chrome mein ye top band karo", "close_tab", "Google Chrome"),
    ("krome mein agale tab pe ja", "next_tab", "Google Chrome"),
    ("krome mein pichhale top bheja", "previous_tab", "Google Chrome"),
])
async def test_real_prisma_browser_slips(text, action, browser, manifest):
    p = await plan(text, manifest)
    assert [(s.tool, s.args.get("action"), s.args.get("browser")) for s in p.steps] == [("browser.control", action, browser)]


async def test_real_prisma_youtube_play(manifest):
    p = await plan("brave mein youtube pay kesariya bajao", manifest)
    assert p.steps[0].tool == "browser.search" and p.steps[0].args == {
        "query": "kesariya", "site": "youtube", "play_first": True, "browser": "Brave Browser"}


@pytest.mark.parametrize("text,tool,args", [
    # real transcripts from the user's Android phone, 10 Nov 2026
    ("resume spotify", "media.control", {"action": "play"}),
    ("play the music on spotify", "media.control", {"action": "play"}),
    ("play kesariya pump spodify", "media.search", {"query": "kesariya"}),
    ("open chat gpt on chrome", "url.open", {"url": "https://chatgpt.com", "browser": "Google Chrome"}),
    ("play kesariya", "media.search", {"query": "kesariya"}),
])
async def test_real_phone_transcripts(text, tool, args, manifest):
    p = await plan(text, manifest)
    assert [(s.tool, s.args) for s in p.steps] == [(tool, args)]


async def test_open_youtube_and_play_inherits_site(manifest):
    p = await plan("open youtube and play kesariya", manifest)
    assert [(s.tool, s.args) for s in p.steps] == [
        ("browser.search", {"query": "kesariya", "site": "youtube", "play_first": True})]


@pytest.mark.parametrize("text,tool,args", [
    ("don't let mac sleep", "system.control", {"action": "keep_awake"}),
    ("Mac ko sone mat do", "system.control", {"action": "keep_awake"}),
    ("mac ko sone mar do", "system.control", {"action": "keep_awake"}),  # real Prisma slip
    ("do ghante tak mac ko jaga ke rakho", "system.control", {"action": "keep_awake", "minutes": 120}),
    ("ab mac ko sone do", "system.control", {"action": "allow_sleep"}),
    ("volume badhao", "system.control", {"action": "volume_up"}),
    ("volume 30 pe kar do", "system.control", {"action": "volume_set", "value": 30}),
    ("awaaz band karo", "system.control", {"action": "mute"}),
    ("brightness kam karo", "system.control", {"action": "brightness_down"}),
    ("brightness 80 percent", "system.control", {"action": "brightness_set", "value": 80}),
    ("dark mode on karo", "system.control", {"action": "dark_mode_on"}),
    ("battery kitni hai", "system.status", {}),
    ("mac lock karo", "system.power", {"action": "lock"}),
    ("laptop band kar do", "system.power", {"action": "shutdown"}),
    ("Perry, volume pachas pe karo", "system.control", {"action": "volume_set", "value": 50}),
])
async def test_mac_controls(text, tool, args, manifest):
    p = await plan(text, manifest)
    assert [(s.tool, s.args) for s in p.steps] == [(tool, args)]


async def test_server_stop_does_not_touch_spotify_mute(manifest):
    p = await plan("spotify mute karo", manifest)
    assert [s.tool for s in p.steps] != ["system.control"]


@pytest.mark.parametrize("text,args", [
    ("open github and search fastapi websockets", {"query": "fastapi websockets", "site": "github"}),
    ("GitHub kholo aur fastapi search karo", {"query": "fastapi", "site": "github"}),
    ("open youtube, search kesariya and play it", {"query": "kesariya", "site": "youtube", "play_first": True}),
    ("YouTube kholo, lofi beats search karo aur pehla video chalao", {"query": "lofi beats", "site": "youtube", "play_first": True}),
    ("open youtube and search arijit singh", {"query": "arijit singh", "site": "youtube"}),
    ("Chrome mein amazon kholo aur wireless mouse search karo", {"query": "wireless mouse", "site": "amazon", "browser": "Google Chrome"}),
    ("is page pe react hooks search karo", {"query": "react hooks", "site": "current"}),
    ("search lofi here", {"query": "lofi", "site": "current"}),
])
async def test_open_site_then_search(text, args, manifest):
    p = await plan(text, manifest)
    assert [(s.tool, s.args) for s in p.steps] == [("browser.search", args)]


async def test_real_prisma_search_here(manifest):
    p = await plan("iss page per lofi search karo", manifest)  # real Prisma output for "is page pe lofi search karo"
    assert [(s.tool, s.args) for s in p.steps] == [("browser.search", {"query": "lofi", "site": "current"})]


@pytest.mark.parametrize("text,tool,args", [
    # real phone transcripts, 10 Nov 2026 (user's own voice through Prisma)
    ("can you open the first video on this tab", "browser.open_result", {"index": 1}),
    ("play the second video", "browser.open_result", {"index": 2}),
    ("open the first video on youtube on brave browser which the tab you have already opened", "browser.open_result",
     {"index": 1, "browser": "Brave Browser"}),
    ("yes youtube per jo tab abhi khola hua hai uska pahala video jv k e clouds ka hai wo chala do", "browser.open_result", {"index": 1}),
    ("play kesariya from spotify", "media.search", {"query": "kesariya"}),
    ("search on instagram devishi", "browser.search", {"query": "devishi", "site": "instagram"}),
])
async def test_real_phone_transcripts_round2(text, tool, args, manifest):
    p = await plan(text, manifest)
    assert [(s.tool, s.args) for s in p.steps] == [(tool, args)]


async def test_search_then_play_second_result(manifest):
    p = await plan("search lofi on youtube and play the second video", manifest)
    assert [(s.tool, s.args) for s in p.steps] == [
        ("browser.search", {"query": "lofi", "site": "youtube"}), ("browser.open_result", {"index": 2})]
