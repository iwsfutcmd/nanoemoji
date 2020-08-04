# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Create an emoji font from a set of SVGs.

UFO handling informed by:
Cosimo's https://gist.github.com/anthrotype/2acbc67c75d6fa5833789ec01366a517
Notes for https://github.com/googlefonts/ufo2ft/pull/359

For COLR:
    Each SVG file represent one base glyph in the COLR font.
    For each glyph, we get a sequence of PaintedLayer.
    To convert to font format we  use the UFO Glyph pen.

Sample usage:
nanoemoji -v 1 $(find ~/oss/noto-emoji/svg -name '*.svg')
nanoemoji $(find ~/oss/twemoji/assets/svg -name '*.svg')
"""
from absl import app
from absl import flags
from absl import logging
from nanoemoji import write_font
from ninja import ninja_syntax
import os
import subprocess
import sys
from typing import Sequence


FLAGS = flags.FLAGS


# internal flags, typically client wouldn't change
flags.DEFINE_string("build_dir", "build/", "Where build runs.")
flags.DEFINE_bool("gen_ninja", True, "Whether to regenerate build.ninja")
flags.DEFINE_bool("exec_ninja", True, "Whether to run ninja.")


def self_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def build_dir() -> str:
    return os.path.abspath(FLAGS.build_dir)


def rel_self(path: str) -> str:
    path = os.path.normpath(os.path.join(self_dir(), path))
    return os.path.relpath(path, self_dir())


def rel_build(path: str) -> str:
    return os.path.relpath(path, build_dir())


def resolve_rel_build(path):
    return os.path.abspath(os.path.join(build_dir(), path))


def write_preamble(nw):
    def module_rule(mod_name, arg_pattern):
        nw.rule(mod_name, f"{sys.executable} -m nanoemoji.{mod_name} {arg_pattern}")

    nw.comment("Generated by nanoemoji")
    nw.newline()

    nw.rule("picosvg", 'picosvg $in > $out || echo "$in failed picosvg"')
    module_rule("write_codepoints", "$in > $out")
    module_rule("write_fea", "$in > $out")

    keep_glyph_names = " --"
    if not FLAGS.keep_glyph_names:
        keep_glyph_names += "no"
    keep_glyph_names += "keep_glyph_names"
    module_rule(
        "write_font",
        f" --upem {FLAGS.upem}"
        + f' --family "{FLAGS.family}"'
        + f" --color_format {FLAGS.color_format}"
        + f" --output {FLAGS.output}"
        + keep_glyph_names
        + " --output_file $out $in",
    )
    nw.newline()


def picosvg_dest(input_svg: str) -> str:
    return os.path.join("picosvg", os.path.basename(input_svg))


def write_picosvg_builds(nw: ninja_syntax.Writer, svg_files: Sequence[str]):
    for svg_file in svg_files:
        nw.build(picosvg_dest(svg_file), "picosvg", rel_build(svg_file))
    nw.newline()


def write_codepointmap_build(nw: ninja_syntax.Writer, svg_files: Sequence[str]):
    dest_file = "codepointmap.csv"
    nw.build(dest_file, "write_codepoints", [rel_build(f) for f in svg_files])
    nw.newline()


def write_fea_build(nw: ninja_syntax.Writer, svg_files: Sequence[str]):
    nw.build("features.fea", "write_fea", "codepointmap.csv")
    nw.newline()


def write_font_build(nw: ninja_syntax.Writer, svg_files: Sequence[str]):
    inputs = ["codepointmap.csv", "features.fea"] + [picosvg_dest(f) for f in svg_files]
    nw.build(
        write_font.output_file(FLAGS.family, FLAGS.output, FLAGS.color_format),
        "write_font",
        inputs,
    )


def _run(argv):
    svg_files = [os.path.abspath(f) for f in argv[1:]]
    if len(set(os.path.basename(f) for f in svg_files)) != len(svg_files):
        sys.exit("Input svgs must have unique names")

    os.makedirs(build_dir(), exist_ok=True)
    build_file = resolve_rel_build("build.ninja")
    if FLAGS.gen_ninja:
        print(f"Generating {os.path.relpath(build_file)}")
        with open(build_file, "w") as f:
            nw = ninja_syntax.Writer(f)
            write_preamble(nw)
            write_picosvg_builds(nw, svg_files)
            write_codepointmap_build(nw, svg_files)
            write_fea_build(nw, svg_files)
            write_font_build(nw, svg_files)

    # TODO: report on failed svgs
    # this is the delta between inputs and picos
    ninja_cmd = ["ninja", "-C", os.path.dirname(build_file)]
    if FLAGS.exec_ninja:
        print(" ".join(ninja_cmd))
        subprocess.run(ninja_cmd, check=True)
    else:
        print("To run:", " ".join(ninja_cmd))

    return


def main():
    # We don't seem to be __main__ when run as cli tool installed by setuptools
    app.run(_run)


if __name__ == "__main__":
    app.run(_run)
