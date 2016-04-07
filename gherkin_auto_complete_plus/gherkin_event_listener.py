import logging
import re

import sublime
import sublime_plugin

from .utilities import gherkin_parser as gp
from .utilities import log_utilities, settings

directories_error = ('Gherkin Auto-Complete Plus:\n\nNo directories are open in'
                     ' Sublime Text and no additional directories were specified'
                     ' in the Package Settings. The settings for this package'
                     ' can be accessed by going to \n\nPreferences -> Package'
                     ' Settings -> Gherkin Auto-Complete Plus -> Settings - User')

keywords = ['given', 'when', 'then']
completions = {}
steps = []

class GherkinEventListener(sublime_plugin.EventListener):
    """ Sublime Text Event Listener """

    def __init__(self):
        self.first_modify = True

    def on_modified(self, view):
        """ Triggers when a sublime.View is modified. If in Gherkin syntax,
            opens Auto-Complete menu and fills with completions.
            lool

        :param sublime.View view: the sublime view
        """
        view_sel = view.sel()
        if not view_sel:
            return

        if not self._is_feature_file(view):
            return

        if self.first_modify:
            # Set up logging -- must be done here because setting file isn't
            # properly loaded at __init__ time
            self._logging_level = settings.get_logging_level()
            logging.basicConfig(level=self._logging_level)
            self._logger = log_utilities.get_logger(__name__, self._logging_level)

            # Update steps
            self._update_steps(view)
            self.first_modify = False

        view.settings().set('auto_complete', False)

        pos = view_sel[0].end()
        next_char = view.substr(sublime.Region(pos - 1, pos))

        if next_char in (' ', '\n'):
            view.run_command('hide_auto_complete')
            return

        view.run_command('hide_auto_complete')
        self._show_auto_complete(view)
        self._fill_completions(view, pos)

    def on_query_completions(self, view, prefix, locations):
        """ Sublime Text Auto-Complete event handler

        Takes the completions that were set in the 'fill_completions' method
        and returns them to the Auto-Complete list.

        :param sublime.View view: the sublime view
        :param str prefix: last word to the left of the cursor
        :param [int] locations: offset from beginning of line

        ^^ None of which are used, but have some documentation anyway.
        """
        _completions = [sug for key, sug in completions.items()]
        completions.clear()

        return sorted(_completions)

    def on_post_save_async(self, view):
        """ Sublime Text 'On File Save' event handler
            Updates the step catolog after file save in Gherkin syntax

        :param sublime.View view: the sublime view
        """
        if self._is_feature_file(view):
            self._update_steps(view)

    def _update_steps(self, view):
        """ Executes the 'run' method of the 'update_steps' module
            and stores the results in the 'steps' variable
        """
        window = view.window()
        target_directories = window.folders()

        # Add directories manually specified in settings
        additional_directories = settings.get_feature_directories()
        target_directories.extend(additional_directories)

        if not target_directories:
            sublime.error_message(directories_error)
            return

        steps.clear()

        parser = gp.GherkinParser(self._logging_level)

        new_steps = parser.run(target_directories)
        steps.extend(new_steps)

    def _is_feature_file(self, view):
        """ Validates that user is in a feature file

        :param sublime.View view: the sublime view
        :rtype: bool
        """
        file_name = view.file_name()
        return file_name and file_name.endswith('.feature')

    def _step_matches_line(self, step_words, line_words):
        """ Validates that words in step match words in line

        :param [str] step_words: words in step definition
        :param [str] line_words: words in current line

        :rtype: bool
        """
        # Skip first word in line because it is a keyword
        line_text = ' '.join(line_words[1:])
        step_text = ' '.join(step_words)

        if len(step_text) >= len(line_text):
            match = True
            for index, char in enumerate(line_text):
                if step_text[index] != char:
                    match = False
            return match
        else:
            return False

    def _format_step(self, step, line_words=[]):
        """ Returns step formatted in snippet notation

        :param str step: step definition
        :param [str] line_words: words in step definition

        :rtype: str
        """
        # Skip first word in line because it is a keyword
        # Skip last word in line so it'll be included in output
        line_text = ' '.join(line_words[1:-1])

        for i in range(len(line_text)):
            step = step.replace(line_text[i], '', 1)
        index = 1
        regex = r'((?:\".+?\")|(?:\'.+?\')|(?:\<.+?\>)|(?:\[number\]))'
        replace_values = re.findall(regex, step)
        for word in replace_values:
            if word[0] == '"':
                step = step.replace(word, '"${' + str(index) + ':input}"', 1)
                index += 1
            elif word[0] == "'":
                step = step.replace(word, "'${" + str(index) + ":input}'", 1)
                index += 1
            elif word[0] == '<':
                step = step.replace(word, '<${' + str(index) + ':input}>', 1)
                index += 1
            elif word[0] == '[':
                step = step.replace(word, '${' + str(index) + ':[number]}', 1)
                index += 1

        return step.strip()

    def _show_auto_complete(self, view):
        """ Opens Auto-Complete manually

        :param sublime.View view: the sublime view
        """
        def _show_auto_complete():
            view.run_command('auto_complete', {
                'disable_auto_insert': True,
                'api_completions_only': True,
                'next_completion_if_showing': False,
                'auto_complete_commit_on_tab': True,
            })
        # Have to set a timeout for some reason
        sublime.set_timeout(_show_auto_complete, 0)

    def _fill_completions(self, view, location):
        """ Prepares completions for auto-complete list

        :param sublime.View view: the sublime view
        :param int location: position of cursor in line
        """
        last_keyword = ''
        current_region = view.line(location)
        current_line_text = view.substr(current_region).strip()
        current_line_words = current_line_text.split()

        # Don't fill completions until after first space is typed
        if ' ' not in current_line_text:
            return

        # If first word is keyword, take that one
        if current_line_words and current_line_words[0].lower() in keywords:
            last_keyword = current_line_words[0].lower()
        # Otherwise, reverse iterate through lines until keyword is found
        else:
            all_lines = view.split_by_newlines(sublime.Region(0, view.size()))
            current_index = all_lines.index(current_region)
            for region in reversed(all_lines[0:current_index]):
                region_text = view.substr(region).lstrip()
                split_line = region_text.split(' ', 1)
                if split_line and split_line[0].lower() in keywords:
                    last_keyword = split_line[0].lower()
                    break

        if not last_keyword:
            self._logger.warning("Could not find 'Given', 'When', or 'Then' in text.")
            return

        for step_type, step in steps:
            if step_type == last_keyword:
                # If only keyword is typed, provide all steps for keyword
                if len(current_line_words) == 1:
                    step_format = self._format_step(step)
                    suggestion = (step + '\t' + step_type, step_format)
                    completions[step] = suggestion

                # If more words typed, check for match
                elif len(current_line_words) > 1:
                    if self._step_matches_line(step.split(), current_line_words):
                        step_format = self._format_step(step, current_line_words)
                        suggestion = (step + '\t' + step_type, step_format)
                        completions[step] = suggestion
