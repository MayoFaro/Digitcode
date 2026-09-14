from digitcode.native.widgets.chip_button import ChipButton


def test_chip_button_shows_its_text(qapp):
    chip = ChipButton("T=6")
    assert chip.text() == "T=6"


def test_chip_button_click_calls_handler(qapp):
    chip = ChipButton("T=6")
    calls = []
    chip.clicked.connect(lambda: calls.append(True))
    chip.click()
    assert calls == [True]


def test_selected_style_differs_from_default(qapp):
    default_chip = ChipButton("A")
    selected_chip = ChipButton("A", selected=True)
    assert default_chip.styleSheet() != selected_chip.styleSheet()


def test_set_state_updates_the_style(qapp):
    chip = ChipButton("A")
    plain_style = chip.styleSheet()
    chip.set_state(selected=True)
    assert chip.styleSheet() != plain_style
