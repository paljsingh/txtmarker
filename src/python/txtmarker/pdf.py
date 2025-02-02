"""
PDF highlighter module
"""

import re
import sys

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTTextBox, LTTextLine

from pdf_annotate import PdfAnnotator, Location, Appearance

from . import base

class Highlighter(base.Highlighter):
    """
    Finds text and adds annotations to PDF files.
    """

    def highlight(self, infile, outfile, highlights, color_index=None, reflags=None):
        annotations = []

        for page, layout in enumerate(extract_pages(infile, laparams=LAParams(line_margin=1.0, char_margin=4.0))):
            elements = []

            # Extract elements
            self.extract(elements, layout)

            # Get formatted page text
            text = self.text(elements)

            for name, query in highlights:
                results = self.search(query, text, reflags)
                for match in results:
                    # Matching indices
                    start, end = sys.maxsize, -1
                    # Unpack start/end line numbers
                    if match:
                        # Get start index, only store min start across subqueries
                        start = text.count("\n", 0, match.start())

                        # Get end index, adjust if ends with newline
                        # Only store max end across subqueries
                        mend = text.count("\n", 0, match.end())
                        end = max(end, mend)

                        # Colors index
                        if color_index is None:
                            color_index = len(annotations) % len(base.COLORS)

                        # Detect if annotation needs to cover multiple columns
                        if elements[start][0][1] < elements[mend][0][1]:
                            eindex = start

                            # Get last element in first column
                            while eindex < end:
                                if elements[eindex][0][1] < elements[end][0][1]:
                                    eindex += 1
                                else:
                                    break

                            # Create annotation for each column
                            annotations.append((name, base.COLORS[color_index], page) + self.layout(elements[start-1:start]))
                            annotations.append((name, base.COLORS[color_index], page) + self.layout(elements[eindex:end+1]))
                        else:
                            # Single column annotation
                            annotations.append((name, base.COLORS[color_index], page) + self.layout(elements[start:end+1]))

        self.annotate(annotations, infile, outfile)

        return annotations

    def extract(self, elements, layout):
        """
        Extracts text lines and associated coordinates.

        Args:
            elements: list that stores extracted elements
            layout: input layout elements to process
        """

        # loop over the object list
        for obj in layout:
            if isinstance(obj, LTTextLine):
                # Get text instance
                text = obj.get_text()

                # Clean common ligatures and unicode chars
                pairs = [("ﬀ", "ff"), ("ﬃ", "ffi"), ("ﬁ", "fi"), ("ﬂ", "fl"), ("\u2010", "-"), ("\u2013", "-")]

                for find, replace in pairs:
                    text = text.replace(find, replace)

                # Apply custom formatting of text
                if self.formatter:
                    text = self.formatter(text)

                # Add newline back to end of lines in case formatter removed them
                if not text.endswith("\n"):
                    text += "\n"

                if text:
                    elements.append((obj.bbox, text))

            # Recursively process text boxes and figures
            if isinstance(obj, LTTextBox):
                self.extract(elements, obj)

    def text(self, elements):
        """
        Concats all text in elements into a single string for searching.

        Args:
            element: list of ((coordinates), text)

        Returns:
            text string
        """

        for x, (_, t) in enumerate(elements):
            if " " in t and t.endswith("-\n") and len(elements) > x + 1:
                # When text is hyphenated, join word back and move to next line
                t, last = t.rsplit(" ", 1)

                t = t + "\n"
                last = last.replace("-\n", "")

                elements[x] = (elements[x][0], t)
                elements[x + 1] = (elements[x + 1][0], last + elements[x + 1][1])

        return "".join([t for _, t in elements])

    def search(self, query, text, reflags=None):
        """
        Searches a text string using input query.

        Args:
            query: query expression
            text: text string to search

        Returns:
            (start, end) indices of matching elements
        """

        if self.formatter:
            query = self.formatter(query)

        if self.chunks > 0:
            # Chunk into subqueries, require at least 50 chars per chunk
            n = max(int(len(query) / self.chunks), 50)
            subqueries = [query[x:x+n] for x in range(0, len(query), n)]

            # Ensure last chunk is n chars or bigger
            if len(subqueries) > 1 and len(subqueries[-1]) < n:
                subqueries[-2] += subqueries[-1]
                subqueries = subqueries[:-1]
        else:
            subqueries = [query]

        allmatches = []
        for subquery in subqueries:
            # Allow any whitespace. Handles newlines.
            subquery = subquery.replace(r"\ ", r"\s").replace(r" ", r"\s")

            if self.chunks > 0:
                # With chunks enabled, allow optional whitespace after each char. Handles newlines.
                subquery = "".join([q + r"\s?" for q in subquery])

            # Search text for matching string, count newlines to get matching line indices
            matches = re.finditer(subquery, text, reflags)
            allmatches.extend(matches)
        return allmatches

    def layout(self, elements):
        """
        Builds a bounding box for an annotation from a list of elements. This method searches the element list
        and finds the left, bottom, right and top coordinates.

        Args:
            elements: list of ((x1, y1, x2, y2), text)

        Returns:
            (left, bottom, right, top) coordinates
        """

        left = min([element[0][0] for element in elements])
        bottom = min([element[0][1] for element in elements])

        right = max([element[0][2] for element in elements])
        top = max([element[0][3] for element in elements])

        return (left, bottom, right, top)

    def annotate(self, annotations, infile, outfile):
        """
        Annotates a file.

        Args:
            annotations: list of annotations (title, rgb color, page #, x1, y1, x2, y2)
            infile: full path to input file
            outfile: full path to output file
        """

        annotator = PdfAnnotator(infile)

        # List of text ranges already defined
        ranges = []

        for title, rgb, page, x1, y1, x2, y2 in annotations:
            # Highlight text
            annotator.add_annotation("square", Location(x1=x1, y1=y1, x2=x2, y2=y2, page=page),
                                     Appearance(fill=rgb + (0.3,), stroke_color=rgb + (0.3, ), stroke_width=0))

            if title:
                # Determine if title text should be in left or right margin
                if x1 < 250:
                    x1, x2 = max(5, x1 - 35), x1
                else:
                    x1, x2 = x2, x2 + 35

                # Calculate center of highlight annotation and offset
                center = y1 + ((y2 - y1) / 2)
                offset = min(max(5, len(title)), 20)

                # Set position of text annotation. Handle column layout conflicts.
                y1, y2 = self.position(ranges, page, x1 >= 250, center, offset)

                # Add title annotation next to highlight
                annotator.add_annotation("text", Location(x1=x1, y1=y1, x2=x2, y2=y2, page=page),
                                         Appearance(fill=rgb + (1,), font_size=7, stroke_width=1, content=title))

                # Register range
                ranges.append((page, 0 if x1 < 250 else 1, y1, y2))

        annotator.write(outfile)

    def position(self, ranges, page, column, center, offset):
        """
        Searches for the closest open range to use for an annotation element.

        Args:
            ranges: list of existing annotation ranges
            page: page to write annotation
            column: column to write annotation
            center: desired center position of annotation
            offset: +/- value to use from center to build layout range

        Returns:
            y1, y2 open vertical range to use for new annotation
        """

        # Initial y1/y2 position
        y1, y2 = center - offset, center + offset

        # Try initial position
        conflicts = self.conflicts(ranges, page, column, y1, y2)

        while conflicts:
            # Try with negative offset
            conflicts = self.conflicts(ranges, page, column, y1 - offset, y2 - offset)
            if not conflicts:
                y1, y2 = y1 - offset, y2 - offset
            else:
                # Try with positive offset
                conflicts = self.conflicts(ranges, page, column, y1 + offset, y2 + offset)
                if not conflicts:
                    y1, y2 = y1 + offset, y2 + offset
                else:
                    # Increase offset
                    offset *= 1.5

        return y1, y2

    def conflicts(self, ranges, page, column, y1, y2):
        """
        Tests y1-y2 range for significant range conflicts on current page/column.

        Args:
            ranges: list of ranges to test
            page: current page
            column: current column
            y1: y start position
            y2: y end position

        Returns:
            True if significant range conflicts exist, False otherwise
        """

        for p, c, start, end in ranges:
            if page == p and column == c and self.overlaps(start, end, y1, y2) > 5:
                return True

        return False

    def overlaps(self, start1, end1, start2, end2):
        """
        Determines if two coordinate sets overlap in range.

        Args:
            start1: range 1 start
            end1: range 1 end
            start2: range 2 start
            end2: range2 end

        Returns:
            number of overlapping coordinates
        """

        return len(set(range(int(start1), int(end1))) & set(range(int(start2), int(end2))))
