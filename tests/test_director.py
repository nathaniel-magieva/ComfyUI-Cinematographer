"""The Director's Panel -- every enum member, every boundary, every auto.

Why this file exists
--------------------

``director.py`` is almost entirely *transcribed* data: nine enum tuples read out
of an evidence set, plus the rules for when a group counts as auto. That makes it
the module most likely to drift silently. Delete ``"noir"`` from ``GENRES`` and a
naive suite still passes, because nothing asserts the list is the list.

So the tests here are written the other way round from usual: the **expected
values are typed out by hand** in the test file, never read back from the module
under test and never built with the same expression the code uses. If a constant
moves, a literal here disagrees with it and the test fails.

Three things get their own attention because they are the honesty surface:

* **Auto must contribute nothing.** A panel where every group is auto must
  produce an empty fragment and an empty conditioning dict. If "auto" leaked a
  default value into the prompt, the product's central claim -- that auto means
  the model decides -- would be false.
* **The enum lists are complete and pinned.** ``COLOUR_PALETTES`` is all 50 of
  50 and ``CAMERA_MOVES`` is all 33 of 33, both transcribed verbatim from the
  first-party schema capture. An earlier revision shipped 8 and 9 respectively
  and asserted ``len < TOTAL``; that assertion was true and the premise behind
  it was false -- the remaining names were in the prose section of the capture
  the whole time. The totals are still asserted separately from the list
  lengths, so a future edit that pads or truncates fails here.
* **A typo is not a custom palette.** ``Molten Dawn`` is a real user-created
  palette and must be accepted *only* with ``custom=True``; a mistyped preset
  must raise rather than silently become a custom palette.
"""

import pytest

from cinematographer import director
from cinematographer.director import (
    APERTURES,
    CAMERA_BODIES,
    COLOUR_PALETTES,
    COLOUR_PALETTES_TOTAL,
    EMOTIONS,
    EMOTION_INTENSITY_MAX,
    EMOTION_INTENSITY_MIN,
    ERAS,
    FOCAL_LENGTH_DROPPED_IN_4_0,
    GENRES,
    LENSES,
    LIGHTING_LOOKS,
    PANEL_FIELDS,
    TEMPOS,
    CameraSetup,
    DirectorPanel,
    EmotionDirection,
    FilmSetup,
    LightingSetup,
    PaletteSetup,
    panel_conditioning,
    panel_prompt_fragment,
    panel_summary,
)

# --------------------------------------------------------------------------
# The constants themselves, spelled out. These are the drift alarms.
# --------------------------------------------------------------------------


def test_genres_are_exactly_the_six_api_values():
    assert GENRES == ("epic", "drama", "noir", "comedy", "horror", "action")
    assert len(GENRES) == 6
    # The UI lists 7 including "general"; the API does not accept it.
    assert "general" not in GENRES


def test_eras_are_exactly_the_five_api_values():
    assert ERAS == ("1960s", "1980s", "1990s", "2000s", "2020s")
    assert len(ERAS) == 5


def test_tempos_are_exactly_the_four_api_pacing_values():
    assert TEMPOS == ("chaotic", "dynamic", "calm", "single-shot")
    assert len(TEMPOS) == 4


def test_camera_bodies_are_exactly_four():
    assert CAMERA_BODIES == ("modern", "35mm-film", "8mm-film", "dv-camcorder")
    assert len(CAMERA_BODIES) == 4


def test_lenses_are_exactly_five():
    assert LENSES == (
        "clean-sharp",
        "anamorphic",
        "vintage-anamorphic",
        "warm-vintage",
        "halation-vintage",
    )
    assert len(LENSES) == 5


def test_apertures_are_exactly_three_and_keep_the_api_typo():
    assert APERTURES == ("f14-wide-open", "f4-moderate", "f11-deep-focus")
    assert len(APERTURES) == 3
    # The API slug is "f14" (a typo for f/1.4). We keep it so the value can be
    # sent unchanged; "f1.4-wide-open" would not be accepted by the API.
    assert "f1.4-wide-open" not in APERTURES


def test_lighting_looks_are_complete_at_six():
    assert LIGHTING_LOOKS == (
        "silhouette",
        "practicals",
        "window",
        "overhead-fall",
        "contre-jour",
        "soft-cross",
    )
    assert len(LIGHTING_LOOKS) == 6


def test_colour_palettes_are_complete_and_match_the_total():
    """The list is the whole enum, not a subset.

    An earlier revision shipped 8 of 50 and asserted ``len < TOTAL``. That
    assertion was true and the premise behind it was false: the other 42 names
    were in the prose section of the schema capture the whole time. The list is
    now transcribed in full, so the two counts must be equal -- and the
    transcription is pinned verbatim below so a future edit that drops,
    reorders, or pads a member fails here rather than silently changing the
    enum.
    """
    assert COLOUR_PALETTES_TOTAL == 50
    assert len(COLOUR_PALETTES) == COLOUR_PALETTES_TOTAL
    assert len(set(COLOUR_PALETTES)) == len(COLOUR_PALETTES)
    assert COLOUR_PALETTES == (
        "static-noon",
        "twilight-fable",
        "back-row-kissing-seats",
        "on-the-other-side-of-the-porthole",
        "the-emerald-ambush",
        "highway-standoff",
        "the-faded-fresco",
        "oil-ochre",
        "the-mountain-convent",
        "ghost-in-the-code",
        "pink-velvet",
        "two-days-to-the-horizon",
        "industrial-fog",
        "stairs-go-up",
        "field-post",
        "home-is-the-next-gas-station",
        "glossy-flesh",
        "the-crimson-ballet",
        "neon-rain-at-midnight",
        "the-morning-after-rain",
        "the-iron-borough",
        "the-ground",
        "the-investigation",
        "turquoise-mirage",
        "a-dream-in-color",
        "breakfast-on-schedule",
        "favela-gold",
        "a-hotel-for-one",
        "after-dark",
        "crimson-vigi",
        "the-neighbors-saw-everything",
        "the-grey-channel",
        "mirage-at-noon",
        "bubblegum-boulevard",
        "yellow-room",
        "the-earth-keeps-things-reluctantly",
        "tropic-fever-dream",
        "bioluminescent-night",
        "dont-turn-it-off-im-watching",
        "the-silk-curtain-falls",
        "the-butterfly",
        "playtime",
        "wallpaper-romance",
        "overtime",
        "the-way-home-is-longer",
        "everyone-speaks-in-whispers",
        "runaway-summer",
        "amber-wasteland",
        "the-circus",
        "gasoline-sunset",
    )
    # A user-created palette is not an enum member. Re-checked against the full
    # 50: every enum member is a lowercase hyphenated slug, so a title-cased or
    # spaced name cannot collide with one.
    assert "Molten Dawn" not in COLOUR_PALETTES
    assert "Nostalgic Blue" not in COLOUR_PALETTES
    assert "dreamy teal" not in COLOUR_PALETTES
    assert "graveyard shift" not in COLOUR_PALETTES
    assert "violet hour" not in COLOUR_PALETTES


def test_emotions_are_the_union_of_the_two_disagreeing_eight_item_lists():
    assert len(EMOTIONS) == 9
    assert EMOTIONS == (
        "Sadness",
        "Fear",
        "Anger",
        "Joy",
        "Trust",
        "Disgust",
        "Surprise",
        "Interest",
        "Hope",
    )
    # The two sources differ by exactly one member each way.
    assert "Interest" in EMOTIONS  # read off the wheel
    assert "Hope" in EMOTIONS  # enumerated by the settings reference


def test_intensity_bounds_are_the_invented_zero_to_one():
    assert EMOTION_INTENSITY_MIN == 0.0
    assert EMOTION_INTENSITY_MAX == 1.0


def test_focal_length_is_recorded_as_dropped_in_4_0():
    assert FOCAL_LENGTH_DROPPED_IN_4_0 is True


def test_panel_fields_are_the_api_names_and_exclude_camera_movement():
    assert PANEL_FIELDS == (
        "genre",
        "era",
        "pacing",
        "camera_model",
        "camera_lens",
        "camera_aperture",
        "light",
        "color_palette",
        "emotion",
    )
    # The move travels in the prompt, not the panel. Emitting it here would
    # misrepresent the mechanism.
    assert "camera_movement" not in PANEL_FIELDS


# --------------------------------------------------------------------------
# Every enum member is accepted, by every group
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", GENRES)
def test_every_genre_is_accepted(value):
    assert FilmSetup(genre=value).genre == value


@pytest.mark.parametrize("value", ERAS)
def test_every_era_is_accepted(value):
    assert FilmSetup(era=value).era == value


@pytest.mark.parametrize("value", TEMPOS)
def test_every_tempo_is_accepted(value):
    assert FilmSetup(pacing=value).pacing == value


@pytest.mark.parametrize("value", CAMERA_BODIES)
def test_every_camera_body_is_accepted(value):
    assert CameraSetup(camera_model=value).camera_model == value


@pytest.mark.parametrize("value", LENSES)
def test_every_lens_is_accepted(value):
    assert CameraSetup(camera_lens=value).camera_lens == value


@pytest.mark.parametrize("value", APERTURES)
def test_every_aperture_is_accepted(value):
    assert CameraSetup(camera_aperture=value).camera_aperture == value


@pytest.mark.parametrize("value", LIGHTING_LOOKS)
def test_every_lighting_look_is_accepted(value):
    assert LightingSetup(light=value).light == value


@pytest.mark.parametrize("value", COLOUR_PALETTES)
def test_every_documented_palette_is_accepted(value):
    assert PaletteSetup(color_palette=value).color_palette == value


@pytest.mark.parametrize("value", EMOTIONS)
def test_every_emotion_is_accepted(value):
    assert EmotionDirection("tamsin", value).emotion == value


# --------------------------------------------------------------------------
# A bad value is rejected, and the message names the value and the legal set
# --------------------------------------------------------------------------


def test_bad_genre_is_rejected_and_names_the_legal_set():
    with pytest.raises(ValueError) as excinfo:
        FilmSetup(genre="general")
    message = str(excinfo.value)
    assert "'general'" in message
    assert "'noir'" in message


def test_bad_era_is_rejected():
    with pytest.raises(ValueError):
        FilmSetup(era="1970s")


def test_bad_tempo_is_rejected():
    with pytest.raises(ValueError):
        FilmSetup(pacing="frantic")


def test_bad_camera_body_is_rejected():
    with pytest.raises(ValueError):
        CameraSetup(camera_model="imax")


def test_bad_lens_is_rejected():
    with pytest.raises(ValueError):
        CameraSetup(camera_lens="fisheye")


def test_bad_aperture_is_rejected():
    with pytest.raises(ValueError):
        CameraSetup(camera_aperture="f2.8")


def test_bad_lighting_look_is_rejected():
    with pytest.raises(ValueError):
        LightingSetup(light="golden-hour")


def test_bad_emotion_is_rejected():
    with pytest.raises(ValueError):
        EmotionDirection("tamsin", "Ennui")


def test_a_mistyped_preset_is_not_silently_a_custom_palette():
    # "static nooon" is a typo, not a user palette. It must raise, or a typo
    # would silently become a custom palette and the preset would never apply.
    with pytest.raises(ValueError) as excinfo:
        PaletteSetup(color_palette="static nooon")
    assert "custom=True" in str(excinfo.value)


def test_a_real_custom_palette_is_accepted_when_declared():
    setup = PaletteSetup(color_palette="Molten Dawn", custom=True)
    assert setup.color_palette == "Molten Dawn"
    assert setup.custom is True


def test_empty_palette_name_is_rejected():
    with pytest.raises(ValueError):
        PaletteSetup(color_palette="   ", custom=True)


def test_empty_character_name_is_rejected():
    with pytest.raises(ValueError):
        EmotionDirection("   ", "Joy")


def test_intensity_without_an_emotion_is_rejected():
    with pytest.raises(ValueError) as excinfo:
        EmotionDirection("tamsin", None, 0.5)
    assert "auto" in str(excinfo.value)


@pytest.mark.parametrize("value", [-0.01, 1.01, 2.0, -1.0])
def test_intensity_outside_zero_to_one_is_rejected(value):
    with pytest.raises(ValueError):
        EmotionDirection("tamsin", "Joy", value)


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
def test_intensity_inside_zero_to_one_is_accepted(value):
    assert EmotionDirection("tamsin", "Joy", value).intensity == value


# --------------------------------------------------------------------------
# defaults() leaves every group auto
# --------------------------------------------------------------------------


def test_defaults_leaves_every_group_auto():
    panel = DirectorPanel.defaults()
    assert panel.film.genre is None
    assert panel.film.era is None
    assert panel.film.pacing is None
    assert panel.camera.camera_model is None
    assert panel.camera.camera_lens is None
    assert panel.camera.camera_aperture is None
    assert panel.lighting.light is None
    assert panel.palette.color_palette is None
    assert panel.emotions == []


def test_defaults_panel_reports_itself_auto():
    assert DirectorPanel.defaults().is_auto() is True


@pytest.mark.parametrize(
    "group, field, value",
    [
        ("film", "genre", "noir"),
        ("film", "era", "1980s"),
        ("film", "pacing", "calm"),
        ("camera", "camera_model", "35mm-film"),
        ("camera", "camera_lens", "anamorphic"),
        ("camera", "camera_aperture", "f4-moderate"),
        ("lighting", "light", "practicals"),
        ("palette", "color_palette", "static-noon"),
    ],
)
def test_setting_any_single_field_makes_the_panel_not_auto(group, field, value):
    panel = DirectorPanel.defaults()
    getattr(panel, group).__setattr__(field, value)
    assert getattr(panel, group).is_auto() is False
    assert panel.is_auto() is False


def test_an_emotion_makes_the_panel_not_auto():
    panel = DirectorPanel.defaults()
    panel.emotions.append(EmotionDirection("tamsin", "Joy"))
    assert panel.is_auto() is False


def test_is_auto_per_group():
    assert FilmSetup().is_auto() is True
    assert FilmSetup(genre="noir").is_auto() is False
    assert CameraSetup().is_auto() is True
    assert CameraSetup(camera_lens="anamorphic").is_auto() is False
    assert LightingSetup().is_auto() is True
    assert LightingSetup(light="practicals").is_auto() is False
    assert PaletteSetup().is_auto() is True
    assert PaletteSetup(color_palette="static-noon").is_auto() is False
    assert EmotionDirection("tamsin").is_auto() is True
    assert EmotionDirection("tamsin", "Joy").is_auto() is False


def test_an_auto_emotion_does_not_make_the_panel_not_auto():
    # A direction with no emotion is auto, so it must not flip the panel.
    panel = DirectorPanel.defaults()
    panel.emotions.append(EmotionDirection("tamsin"))
    assert panel.emotions[0].is_auto() is True
    assert panel.is_auto() is True


# --------------------------------------------------------------------------
# An all-auto panel contributes nothing
# --------------------------------------------------------------------------


def test_all_auto_panel_produces_an_empty_fragment():
    assert panel_prompt_fragment(DirectorPanel.defaults()) == ""


def test_all_auto_panel_produces_an_empty_conditioning_dict():
    assert panel_conditioning(DirectorPanel.defaults()) == {}


def test_all_auto_panel_summary_says_auto_out_loud():
    assert panel_summary(DirectorPanel.defaults()) == (
        "director panel: all groups auto (contributes nothing)"
    )


def test_an_auto_emotion_contributes_nothing_to_the_fragment():
    panel = DirectorPanel.defaults()
    panel.emotions.append(EmotionDirection("tamsin"))
    assert panel_prompt_fragment(panel) == ""


def test_an_auto_emotion_is_absent_from_conditioning():
    panel = DirectorPanel.defaults()
    panel.emotions.append(EmotionDirection("tamsin"))
    assert panel_conditioning(panel) == {}


# --------------------------------------------------------------------------
# The fragment, spelled out by hand
# --------------------------------------------------------------------------


def test_fragment_for_a_fully_set_panel_is_exactly_this_string():
    panel = DirectorPanel(
        film=FilmSetup(genre="noir", era="1980s", pacing="calm"),
        camera=CameraSetup(
            camera_model="35mm-film",
            camera_lens="anamorphic",
            camera_aperture="f4-moderate",
        ),
        lighting=LightingSetup(light="practicals"),
        palette=PaletteSetup(color_palette="static-noon"),
        emotions=[EmotionDirection("tamsin", "Joy", 0.5)],
    )
    assert panel_prompt_fragment(panel) == (
        "genre noir, era 1980s, pacing calm, camera 35mm-film, lens anamorphic, "
        "aperture f4-moderate, lighting practicals, palette static-noon, "
        "@tamsin Joy 0.5"
    )


def test_fragment_omits_auto_axes_but_keeps_the_set_ones():
    panel = DirectorPanel(film=FilmSetup(genre="noir"))
    assert panel_prompt_fragment(panel) == "genre noir"


def test_fragment_for_an_emotion_without_intensity_has_no_number():
    panel = DirectorPanel(emotions=[EmotionDirection("tamsin", "Joy")])
    assert panel_prompt_fragment(panel) == "@tamsin Joy"


def test_fragment_is_ascii_only_and_transliterates():
    panel = DirectorPanel(emotions=[EmotionDirection("Zoë", "Joy")])
    fragment = panel_prompt_fragment(panel)
    assert fragment == "@Zoe Joy"
    assert fragment.isascii()


def test_fragment_orders_emotions_as_given():
    panel = DirectorPanel(
        emotions=[
            EmotionDirection("tamsin", "Joy"),
            EmotionDirection("oscar", "Fear"),
        ]
    )
    assert panel_prompt_fragment(panel) == "@tamsin Joy, @oscar Fear"


# --------------------------------------------------------------------------
# Conditioning, spelled out by hand
# --------------------------------------------------------------------------


def test_conditioning_uses_the_api_field_names():
    panel = DirectorPanel(
        film=FilmSetup(genre="noir", era="1980s", pacing="calm"),
        camera=CameraSetup(
            camera_model="35mm-film",
            camera_lens="anamorphic",
            camera_aperture="f4-moderate",
        ),
        lighting=LightingSetup(light="practicals"),
        palette=PaletteSetup(color_palette="static-noon"),
        emotions=[EmotionDirection("tamsin", "Joy", 0.5)],
    )
    assert panel_conditioning(panel) == {
        "genre": "noir",
        "era": "1980s",
        "pacing": "calm",
        "camera_model": "35mm-film",
        "camera_lens": "anamorphic",
        "camera_aperture": "f4-moderate",
        "light": "practicals",
        "color_palette": "static-noon",
        "emotion": [{"character": "tamsin", "emotion": "Joy", "intensity": 0.5}],
    }


def test_conditioning_omits_auto_fields_entirely():
    panel = DirectorPanel(film=FilmSetup(era="1980s"))
    assert panel_conditioning(panel) == {"era": "1980s"}


def test_conditioning_never_emits_camera_movement():
    panel = DirectorPanel(
        camera=CameraSetup(camera_model="modern"),
        lighting=LightingSetup(light="window"),
    )
    assert "camera_movement" not in panel_conditioning(panel)


# --------------------------------------------------------------------------
# to_dict / from_dict round-trip, keyed by the API names
# --------------------------------------------------------------------------


def test_to_dict_is_flat_and_keyed_by_api_names():
    panel = DirectorPanel(
        film=FilmSetup(genre="noir"),
        camera=CameraSetup(camera_lens="anamorphic"),
        lighting=LightingSetup(light="practicals"),
        palette=PaletteSetup(color_palette="static-noon"),
        emotions=[EmotionDirection("tamsin", "Joy", 0.25)],
    )
    assert panel.to_dict() == {
        "genre": "noir",
        "era": None,
        "pacing": None,
        "camera_model": None,
        "camera_lens": "anamorphic",
        "camera_aperture": None,
        "light": "practicals",
        "color_palette": "static-noon",
        "emotion": [{"character": "tamsin", "emotion": "Joy", "intensity": 0.25}],
    }


def test_to_dict_keys_are_exactly_panel_fields():
    assert tuple(DirectorPanel.defaults().to_dict()) == PANEL_FIELDS


def test_round_trip_through_dict_is_lossless():
    panel = DirectorPanel(
        film=FilmSetup(genre="epic", era="2020s", pacing="single-shot"),
        camera=CameraSetup(
            camera_model="8mm-film",
            camera_lens="halation-vintage",
            camera_aperture="f11-deep-focus",
        ),
        lighting=LightingSetup(light="contre-jour"),
        palette=PaletteSetup(color_palette="gasoline-sunset"),
        emotions=[EmotionDirection("oscar", "Fear", 1.0)],
    )
    assert DirectorPanel.from_dict(panel.to_dict()).to_dict() == panel.to_dict()


def test_from_dict_rejects_an_unknown_field():
    with pytest.raises(ValueError) as excinfo:
        DirectorPanel.from_dict({"genre": "noir", "nope": 1})
    assert "nope" in str(excinfo.value)


def test_from_dict_rejects_a_non_dict():
    with pytest.raises(ValueError):
        DirectorPanel.from_dict(["genre"])


def test_from_dict_rejects_a_bad_value_through_the_group():
    with pytest.raises(ValueError):
        DirectorPanel.from_dict({"genre": "general"})


def test_from_dict_rejects_a_non_list_emotion():
    with pytest.raises(ValueError):
        DirectorPanel.from_dict({"emotion": "Joy"})


def test_group_from_dict_rejects_unknown_fields():
    with pytest.raises(ValueError):
        FilmSetup.from_dict({"genre": "noir", "tempo": "calm"})
    with pytest.raises(ValueError):
        CameraSetup.from_dict({"lens": "anamorphic"})
    with pytest.raises(ValueError):
        LightingSetup.from_dict({"lighting": "window"})
    with pytest.raises(ValueError):
        PaletteSetup.from_dict({"palette": "static-noon"})
    with pytest.raises(ValueError):
        EmotionDirection.from_dict({"name": "tamsin"})


def test_emotion_from_dict_requires_a_character():
    with pytest.raises(ValueError):
        EmotionDirection.from_dict({"emotion": "Joy"})


# --------------------------------------------------------------------------
# direction_for
# --------------------------------------------------------------------------


def test_direction_for_finds_the_character_case_insensitively():
    panel = DirectorPanel(emotions=[EmotionDirection("Tamsin", "Joy")])
    found = panel.direction_for("tamsin")
    assert found is not None
    assert found.emotion == "Joy"


def test_direction_for_returns_none_when_absent():
    assert DirectorPanel.defaults().direction_for("nobody") is None


def test_direction_for_transliterates_the_lookup():
    panel = DirectorPanel(emotions=[EmotionDirection("Zoë", "Joy")])
    assert panel.direction_for("Zoe") is not None


# --------------------------------------------------------------------------
# summary
# --------------------------------------------------------------------------


def test_summary_names_every_axis_and_says_auto_where_unset():
    panel = DirectorPanel(film=FilmSetup(genre="noir"))
    assert panel_summary(panel) == (
        "director panel: genre=noir, era=auto, pacing=auto, camera=auto, "
        "lens=auto, aperture=auto, light=auto, palette=auto"
    )


def test_summary_is_ascii_only():
    panel = DirectorPanel(emotions=[EmotionDirection("Zoë", "Joy", 0.5)])
    assert panel_summary(panel).isascii()


def test_summary_reports_an_emotion_intensity_when_one_was_given():
    """An intensity is only meaningful if the summary actually shows it.

    Without this, a panel directed at 0.5 and a panel directed at 1.0 would
    summarise identically, and the reader could not tell which was asked for.
    """
    panel = DirectorPanel(emotions=[EmotionDirection("tamsin", "Joy", 0.5)])
    assert "@tamsin=Joy@0.5" in panel_summary(panel)


def test_summary_omits_the_intensity_when_none_was_given():
    """The other side of the same branch: no intensity, no `@` suffix."""
    panel = DirectorPanel(emotions=[EmotionDirection("oscar", "Fear")])
    summary = panel_summary(panel)
    assert "@oscar=Fear" in summary
    assert "@oscar=Fear@" not in summary


def test_summary_distinguishes_directed_intensities():
    """Two panels differing only in intensity must not summarise the same."""
    low = DirectorPanel(emotions=[EmotionDirection("tamsin", "Joy", 0.25)])
    high = DirectorPanel(emotions=[EmotionDirection("tamsin", "Joy", 1.0)])
    assert panel_summary(low) != panel_summary(high)


def test_module_exposes_the_documented_names():
    for name in (
        "GENRES",
        "ERAS",
        "TEMPOS",
        "CAMERA_BODIES",
        "LENSES",
        "APERTURES",
        "LIGHTING_LOOKS",
        "COLOUR_PALETTES",
        "EMOTIONS",
        "FilmSetup",
        "CameraSetup",
        "LightingSetup",
        "PaletteSetup",
        "EmotionDirection",
        "DirectorPanel",
        "panel_prompt_fragment",
        "panel_conditioning",
        "panel_summary",
    ):
        assert hasattr(director, name), name
