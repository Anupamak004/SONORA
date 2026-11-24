"""Configurable instrument preservation profiles prioritizing musical fidelity."""

from __future__ import annotations

from app.models.schemas import InstrumentProfile

_INSTRUMENT_PROFILES: tuple[InstrumentProfile, ...] = (
    InstrumentProfile(
        id="general",
        name="General / Balanced Instrument",
        description=(
            "Balanced protection for mixed or unspecified acoustic and electric instruments. "
            "Preserves broad fundamental range, harmonics, and natural decay."
        ),
        fundamental_min_hz=40.0,
        fundamental_max_hz=4200.0,
        default_hpf_hz=35.0,
        min_hpf_hz=20.0,
        max_hpf_hz=120.0,
        protect_fundamentals=True,
        protect_harmonics=True,
        pitch_safe_hum_guard=True,
        transient_protection=0.75,
        default_attenuation_limit_db=12.0,
        default_strength=0.55,
        hum_conflict_note=(
            "Pitch-safe hum guard dynamically tightens notch depth when sustained notes "
            "overlap 50/60 Hz or their lower harmonics."
        ),
    ),
    InstrumentProfile(
        id="acoustic_guitar",
        name="Acoustic Guitar / Plucked Strings",
        description=(
            "Protects sharp pick/finger attack transients, woody body resonance, "
            "and delicate string decay tails."
        ),
        fundamental_min_hz=82.4,
        fundamental_max_hz=1318.5,
        default_hpf_hz=68.0,
        min_hpf_hz=40.0,
        max_hpf_hz=120.0,
        protect_fundamentals=True,
        protect_harmonics=True,
        pitch_safe_hum_guard=True,
        transient_protection=0.90,
        default_attenuation_limit_db=12.0,
        default_strength=0.55,
        hum_conflict_note=(
            "Low E2 (82.4 Hz) sits safely above 50/60 Hz, while A2/B2/D3 can sit near "
            "100/120/150 Hz hum harmonics; pitch-safe harmonic guarding remains enabled."
        ),
    ),
    InstrumentProfile(
        id="piano",
        name="Piano / Keys",
        description=(
            "Full-bandwidth protection from sub-bass A0 (27.5 Hz) to upper hammer brilliance, "
            "preserving sustain pedal decay and quiet passages."
        ),
        fundamental_min_hz=27.5,
        fundamental_max_hz=4186.0,
        default_hpf_hz=24.0,
        min_hpf_hz=18.0,
        max_hpf_hz=80.0,
        protect_fundamentals=True,
        protect_harmonics=True,
        pitch_safe_hum_guard=True,
        transient_protection=0.85,
        default_attenuation_limit_db=10.0,
        default_strength=0.50,
        hum_conflict_note=(
            "Piano fundamentals directly overlap 50/60 Hz (G1=49 Hz, B1=61.7 Hz) and harmonics; "
            "pitch-safe narrow-Q hum notching is mandatory to avoid hollowing left-hand notes."
        ),
    ),
    InstrumentProfile(
        id="bowed_strings",
        name="Bowed Strings (Violin / Viola / Cello)",
        description=(
            "Prioritizes continuous harmonic overtones, bow articulation, vibrato smoothness, "
            "and quiet sustained notes without watery gating."
        ),
        fundamental_min_hz=65.4,
        fundamental_max_hz=3520.0,
        default_hpf_hz=55.0,
        min_hpf_hz=35.0,
        max_hpf_hz=180.0,
        protect_fundamentals=True,
        protect_harmonics=True,
        pitch_safe_hum_guard=True,
        transient_protection=0.65,
        default_attenuation_limit_db=10.0,
        default_strength=0.45,
        hum_conflict_note=(
            "Cello low C2 (65.4 Hz) and lower harmonics sit close to 60/120/180 Hz; "
            "ultra-narrow pitch-safe notching protects bowed sustain."
        ),
    ),
    InstrumentProfile(
        id="wind_brass",
        name="Woodwinds & Brass",
        description=(
            "Preserves natural breath tone, expressive dynamic swells, formant richness, "
            "and soft pianissimo entrances."
        ),
        fundamental_min_hz=58.3,
        fundamental_max_hz=2637.0,
        default_hpf_hz=48.0,
        min_hpf_hz=25.0,
        max_hpf_hz=150.0,
        protect_fundamentals=True,
        protect_harmonics=True,
        pitch_safe_hum_guard=True,
        transient_protection=0.70,
        default_attenuation_limit_db=11.0,
        default_strength=0.50,
        hum_conflict_note=(
            "Gentle breath air above 4 kHz can resemble broadband hiss; conservative attenuation "
            "limits protect tonal realism."
        ),
    ),
    InstrumentProfile(
        id="percussion",
        name="Percussion & Drums",
        description=(
            "Maximum transient preservation for crisp stick attacks, snare snap, "
            "and natural cymbal shimmer decay."
        ),
        fundamental_min_hz=40.0,
        fundamental_max_hz=8000.0,
        default_hpf_hz=32.0,
        min_hpf_hz=20.0,
        max_hpf_hz=100.0,
        protect_fundamentals=True,
        protect_harmonics=True,
        pitch_safe_hum_guard=True,
        transient_protection=0.95,
        default_attenuation_limit_db=12.0,
        default_strength=0.50,
        hum_conflict_note=(
            "Kick and tom fundamentals can overlap 50–120 Hz; pitch-safe hum notching "
            "uses narrow Q to preserve low-end punch."
        ),
    ),
    InstrumentProfile(
        id="bass",
        name="Bass Guitar / Upright Bass",
        description=(
            "Protects deep low-end fundamentals down to 41 Hz (and low B0 at 31 Hz when configured) "
            "and finger/pick definition."
        ),
        fundamental_min_hz=41.2,
        fundamental_max_hz=400.0,
        default_hpf_hz=28.0,
        min_hpf_hz=20.0,
        max_hpf_hz=60.0,
        protect_fundamentals=True,
        protect_harmonics=True,
        pitch_safe_hum_guard=True,
        transient_protection=0.80,
        default_attenuation_limit_db=10.0,
        default_strength=0.45,
        hum_conflict_note=(
            "Bass fundamentals directly overlap 50/60 Hz and harmonics (G1=49 Hz, B1=61.7 Hz); "
            "hum removal is strictly pitch-conflict-guarded and conservative."
        ),
    ),
)

_PROFILE_BY_ID: dict[str, InstrumentProfile] = {
    profile.id: profile for profile in _INSTRUMENT_PROFILES
}


def list_profiles() -> list[InstrumentProfile]:
    """Return all configured instrument preservation profiles."""
    return list(_INSTRUMENT_PROFILES)


def get_profile(profile_id: str) -> InstrumentProfile | None:
    """Lookup an instrument profile by ID."""
    return _PROFILE_BY_ID.get(profile_id)
