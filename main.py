from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.clock import Clock, mainthread
import threading
import time
import os
from moviepy.editor import VideoFileClip
from queue import Queue


class FileWidget(BoxLayout):
    def __init__(self, video_path, default_output_name, on_delete, on_edit, **kwargs):
        super().__init__(orientation='vertical', size_hint_y=None, height=150, **kwargs)
        self.video_path = video_path
        self.default_output_name = default_output_name
        self.on_delete = on_delete
        self.on_edit = on_edit

        # File name and progress bar
        self.file_label = Label(text=os.path.basename(video_path), size_hint=(1, None), height=30)
        self.add_widget(self.file_label)

        self.progress_bar = ProgressBar(max=100, value=0, size_hint=(1, None), height=20)
        self.add_widget(self.progress_bar)

        # Output name input
        self.output_name_input = TextInput(
            text=default_output_name, multiline=False, size_hint=(1, None), height=30, opacity=0
        )  # Hidden by default
        self.add_widget(self.output_name_input)

        # Edit and delete buttons
        button_layout = BoxLayout(orientation='horizontal', size_hint=(1, None), height=40, spacing=10)
        self.edit_button = Button(text="Edit", size_hint=(1, None), height=40)
        self.edit_button.bind(on_press=self.toggle_name_input)
        self.delete_button = Button(text="Hapus", size_hint=(1, None), height=40)
        self.delete_button.bind(on_press=lambda _: on_delete(self))

        button_layout.add_widget(self.edit_button)
        button_layout.add_widget(self.delete_button)
        self.add_widget(button_layout)

    def disable_controls(self):
        self.output_name_input.disabled = True
        self.edit_button.disabled = True
        self.delete_button.disabled = True

    def enable_controls(self):
        self.output_name_input.disabled = False
        self.edit_button.disabled = False
        self.delete_button.disabled = False

    def toggle_name_input(self, instance):
        if self.edit_button.text == "Edit":
            # Switch to Save mode
            self.edit_button.text = "Save"
            self.output_name_input.opacity = 1
            self.file_label.opacity = 0
        else:
            # Save the new name and switch back to Edit mode
            self.edit_button.text = "Edit"
            new_name = self.output_name_input.text.strip()
            if new_name:  # Only update if the input is not empty
                self.file_label.text = new_name
            self.output_name_input.opacity = 0
            self.file_label.opacity = 1

    @mainthread
    def update_progress(self, value):
        self.progress_bar.value = value


class ConverterApp(App):
    def build(self):
        self.layout = BoxLayout(orientation='vertical', padding=10, spacing=10)

        self.select_file_button = Button(text="Pilih File MP4", size_hint=(1, None), height=50)
        self.select_file_button.bind(on_press=self.open_file_chooser)
        self.layout.add_widget(self.select_file_button)

        self.scroll_view = ScrollView(size_hint=(1, None), height=400)  # Adjust height to be more responsive
        self.file_list = GridLayout(cols=1, size_hint_y=None, spacing=10)
        self.file_list.bind(minimum_height=self.file_list.setter('height'))
        self.scroll_view.add_widget(self.file_list)
        self.layout.add_widget(self.scroll_view)

        self.convert_button = Button(text="Convert to MP3", size_hint=(1, None), height=50, disabled=True)  # Disabled by default
        self.convert_button.bind(on_press=self.start_conversion)
        self.layout.add_widget(self.convert_button)

        self.cancel_button = Button(text="Batal", size_hint=(1, None), height=50, disabled=True)
        self.cancel_button.bind(on_press=self.cancel_conversion)
        self.layout.add_widget(self.cancel_button)

        self.file_widgets = []
        self.cancel_event = threading.Event()
        self.is_conversion_in_progress = False
        self.current_conversion_index = 0  # To keep track of which file is being converted

        self.queue = Queue()  # Queue for updating progress in the main thread
        threading.Thread(target=self.process_queue, daemon=True).start()

        return self.layout

    def open_file_chooser(self, instance):
        from plyer import filechooser
        filechooser.open_file(on_selection=self.add_files, filters=["*.mp4"], multiple=True)

    def add_files(self, selection):
        if selection:
            # Add files one by one with a delay to improve UI performance
            for i, video_path in enumerate(selection):
                Clock.schedule_once(lambda dt, path=video_path: self.add_file(path), i * 0.1)

            # Enable convert button if there are files in the list and no conversion is in progress
            if not self.is_conversion_in_progress:
                self.convert_button.disabled = False

    def add_file(self, video_path):
        default_output_name, _ = os.path.splitext(os.path.basename(video_path))
        file_widget = FileWidget(video_path, default_output_name, self.delete_file, self.edit_file)
        self.file_widgets.append(file_widget)
        self.file_list.add_widget(file_widget)

    def delete_file(self, file_widget):
        self.file_widgets.remove(file_widget)
        self.file_list.remove_widget(file_widget)

        # Disable convert button if no files are left
        if not self.file_widgets:
            self.convert_button.disabled = True

    def edit_file(self, file_widget):
        file_widget.toggle_name_input()

    def start_conversion(self, instance):
        if self.file_widgets and not self.is_conversion_in_progress:
            self.is_conversion_in_progress = True
            self.convert_button.disabled = True
            self.cancel_button.disabled = False
            self.cancel_event.clear()
            self.current_conversion_index = 0  # Start from the first file
            threading.Thread(target=self.convert_videos, daemon=True).start()

    def cancel_conversion(self, instance):
        self.cancel_event.set()
        self.cancel_button.disabled = True

        # Keep the file widgets and allow resuming
        for file_widget in self.file_widgets:
            file_widget.enable_controls()

        # Re-enable the convert button
        self.convert_button.disabled = False
        self.is_conversion_in_progress = False

    def convert_videos(self):
        try:
            # Process files starting from the current index
            for i in range(self.current_conversion_index, len(self.file_widgets)):
                if self.cancel_event.is_set():
                    break  # Stop conversion if canceled

                file_widget = self.file_widgets[i]

                # Skip converted files
                if file_widget.progress_bar.value == 100:
                    continue

                file_widget.disable_controls()

                output_path = os.path.join(
                    os.path.dirname(file_widget.video_path),
                    f"{file_widget.output_name_input.text.strip()}.mp3"
                )

                video = VideoFileClip(file_widget.video_path)
                duration = video.duration

                def update_progress(current_time):
                    progress = int((current_time / duration) * 100)
                    self.queue.put((file_widget, progress))  # Update via queue

                    if progress == 100:
                        self.queue.put((file_widget, 100))  # Ensure 100% is reported

                audio = video.audio

                for i in range(1, int(duration) + 1):
                    if self.cancel_event.is_set():
                        break
                    time.sleep(1)  # Simulate processing
                    update_progress(i)

                if not self.cancel_event.is_set():
                    audio.write_audiofile(output_path)
                    self.remove_completed_file(file_widget)  # Automatically remove the file after conversion

            if not self.cancel_event.is_set():
                self.finish_conversion(self)
        except Exception as e:
            print(f"Error: {str(e)}")
            if "graphics instruction" in str(e):
                print("Retrying conversion due to thread error.")
                self.retry_conversion()

    def process_queue(self):
        while True:
            file_widget, progress = self.queue.get()
            if progress == 100:
                file_widget.update_progress(progress)
            else:
                file_widget.update_progress(progress)

    def remove_completed_file(self, file_widget):
        self.file_widgets.remove(file_widget)
        self.file_list.remove_widget(file_widget)

    def finish_conversion(self, instance):
        self.is_conversion_in_progress = False
        self.convert_button.disabled = False
        self.cancel_button.disabled = True


if __name__ == "__main__":
    ConverterApp().run()
