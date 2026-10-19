"""Synthetic demo transcripts. All names and identifiers are fictional."""

from app.schemas.responses import SampleTranscript

SAMPLES: list[SampleTranscript] = [
    SampleTranscript(
        id="appointment-standard",
        title="Appointment request (standard)",
        description="Name and patient ID are redacted; the sanitized payload may reach CloudLink.",
        profile="standard",
        channel="voice",
        transcript="My name is John Smith, my patient ID is 48291, and I need help with my appointment.",
    ),
    SampleTranscript(
        id="appointment-healthcare",
        title="Appointment request (healthcare local-only)",
        description="The same transcript under the healthcare profile is restricted to local processing.",
        profile="healthcare",
        channel="voice",
        transcript="My name is John Smith, my patient ID is 48291, and I need help with my appointment.",
    ),
    SampleTranscript(
        id="appointment-restricted",
        title="Appointment request (restricted)",
        description="The restricted profile blocks all AI processing for patient data.",
        profile="restricted",
        channel="voice",
        transcript="My name is John Smith, my patient ID is 48291, and I need help with my appointment.",
    ),
    SampleTranscript(
        id="contact-update",
        title="Contact details update",
        description="Phone number, email address and name are redacted before processing.",
        profile="standard",
        channel="chat",
        transcript=(
            "Hi, this is Maria Gonzalez. Please update my contact details. My new phone number is "
            "416-555-0199 and my email is maria.gonzalez@example.com. Thanks for your help."
        ),
    ),
    SampleTranscript(
        id="billing-account",
        title="Billing enquiry with account number",
        description="Account numbers keep processing on local infrastructure.",
        profile="standard",
        channel="voice",
        transcript=(
            "Hello, I'm calling about a duplicate charge on my bill. My account number is 7730-1142-9981 "
            "and I would like the second charge reversed."
        ),
    ),
    SampleTranscript(
        id="government-id",
        title="Identity verification with SSN",
        description="Government identifiers block AI processing entirely.",
        profile="standard",
        channel="voice",
        transcript=(
            "For verification my social security number is 512-44-7321. I need to reset the PIN on my "
            "voicemail box."
        ),
    ),
    SampleTranscript(
        id="clean-question",
        title="General question (no sensitive data)",
        description="No sensitive entities; the baseline policy allows cloud handoff.",
        profile="standard",
        channel="chat",
        transcript="Hi, what are your support hours, and can I book a callback with the billing team?",
    ),
    SampleTranscript(
        id="hinglish-triage",
        title="Hinglish triage call (healthcare)",
        description="Hinglish call with a name, date of birth, Indian mobile number and health terms.",
        profile="standard",
        channel="voice",
        transcript=(
            "Hello, main Priya Sharma bol rahi hoon. Meri date of birth 14/03/1986 hai aur patient ID P9048213 hai. "
            "Mujhe diabetes hai aur kal se chest pain ho raha hai. Please mujhe Thursday ka appointment chahiye, "
            "mera number +91 98450 12345 hai."
        ),
    ),
    SampleTranscript(
        id="reschedule-dob",
        title="Reschedule with date of birth",
        description="Name, date of birth and patient ID are tokenized; the summary is re-hydrated for the agent.",
        profile="standard",
        channel="voice",
        transcript=(
            "Hi, this is Daniel Okafor, date of birth March 2, 1979, patient ID 77120. I need to move my dialysis "
            "appointment from Monday to Wednesday afternoon. Daniel Okafor again, thanks."
        ),
    ),
]
