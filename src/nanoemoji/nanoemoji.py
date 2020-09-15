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
from nanoemoji import codepoints
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
flags.DEFINE_bool(
    "gen_svg_font_diffs", False, "Whether to generate svg vs font render diffs."
)
flags.DEFINE_integer("svg_font_diff_resolution", 256, "Render diffs resolution")
flags.DEFINE_bool("exec_ninja", True, "Whether to run ninja.")


def self_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def build_dir() -> str:
    return os.path.abspath(FLAGS.build_dir)


# portable way to say '/'
_FILESYSTEM_ROOT_PATH = os.path.abspath(os.sep)


def rel_build(path: str) -> str:
    path = os.path.abspath(path)
    build_path = build_dir()
    # if the build path is out-of-source and doesn't share any common prefix
    # with source path, relative paths as created by os.path.relpath would reach
    # beyond the filesystem root thus creating issues with ninja; plus, they aren't
    # shorter than equivalent absolute paths, so we prefer the latter in this case.
    prefix = os.path.commonpath([path, build_path])
    if prefix == _FILESYSTEM_ROOT_PATH:
        return path
    return os.path.relpath(path, build_path)


def resolve_rel_build(path):
    return os.path.abspath(os.path.join(build_dir(), path))


def write_preamble(nw):
    def module_rule(mod_name, arg_pattern, rspfile=None, rspfile_content=None):
        nw.rule(
            mod_name,
            f"{sys.executable} -m nanoemoji.{mod_name} {arg_pattern}",
            rspfile=rspfile,
            rspfile_content=rspfile_content,
        )

    nw.comment("Generated by nanoemoji")
    nw.newline()

    nw.rule("picosvg", "picosvg $in > $out")
    module_rule(
        "write_codepoints",
        "@$out.rsp > $out",
        rspfile="$out.rsp",
        rspfile_content="$in",
    )
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
        + " --output_file $out"
        + " @$out.rsp",
        rspfile="$out.rsp",
        rspfile_content="$in",
    )
    if FLAGS.gen_svg_font_diffs:
        nw.rule(
            "write_svg2png",
            f"resvg -h {FLAGS.svg_font_diff_resolution}  -w {FLAGS.svg_font_diff_resolution} $in $out",
        )
        module_rule(
            "write_font2png",
            f"--height {FLAGS.svg_font_diff_resolution}  --width {FLAGS.svg_font_diff_resolution} --output_file $out $in",
        )
        module_rule("write_pngdiff", f"--output_file $out $in")
        module_rule(
            "write_diffreport",
            f"--lhs_dir resvg_png --rhs_dir skia_png --output_file $out @$out.rsp",
            rspfile="$out.rsp",
            rspfile_content="$in",
        )
    nw.newline()


def picosvg_dest(input_svg: str) -> str:
    return os.path.join("picosvg", os.path.basename(input_svg))


def resvg_png_dest(input_svg: str) -> str:
    dest_file = os.path.splitext(os.path.basename(input_svg))[0] + ".png"
    return os.path.join("resvg_png", dest_file)


def font_dest() -> str:
    if FLAGS.output_file is not None:
        return os.path.abspath(FLAGS.output_file)
    else:
        return write_font.output_file(FLAGS.family, FLAGS.output, FLAGS.color_format)


def skia_png_dest(input_svg: str) -> str:
    dest_file = os.path.splitext(os.path.basename(input_svg))[0] + ".png"
    return os.path.join("skia_png", dest_file)


def diff_png_dest(input_svg: str) -> str:
    dest_file = os.path.splitext(os.path.basename(input_svg))[0] + ".png"
    return os.path.join("diff_png", dest_file)


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
    nw.build(font_dest(), "write_font", inputs)
    nw.newline()


def write_svg_font_diff_build(nw: ninja_syntax.Writer, svg_files: Sequence[str]):
    picosvgs = [picosvg_dest(f) for f in svg_files]

    # render each svg => png
    for svg_file in svg_files:
        nw.build(resvg_png_dest(svg_file), "write_svg2png", rel_build(svg_file))
    nw.newline()

    # render each input from the font => png
    for svg_file in svg_files:
        inputs = [
            font_dest(),
            rel_build(svg_file),
        ]
        nw.build(skia_png_dest(svg_file), "write_font2png", inputs)
    nw.newline()

    # create comparison images
    for svg_file in svg_files:
        inputs = [
            resvg_png_dest(svg_file),
            skia_png_dest(svg_file),
        ]
        nw.build(diff_png_dest(svg_file), "write_pngdiff", inputs)
    nw.newline()

    # write report and kerplode if there are bad diffs
    nw.build("diffs.html", "write_diffreport", [diff_png_dest(f) for f in svg_files])
    nw.newline()


def _run(argv):
    svg_files = [os.path.abspath(f) for f in argv[1:]]
    if len(set(os.path.basename(f) for f in svg_files)) != len(svg_files):
        sys.exit("Input svgs must have unique names")

    os.makedirs(build_dir(), exist_ok=True)
    if FLAGS.gen_svg_font_diffs:
        os.makedirs(os.path.join(build_dir(), "resvg_png"), exist_ok=True)
        os.makedirs(os.path.join(build_dir(), "skia_png"), exist_ok=True)
        os.makedirs(os.path.join(build_dir(), "diff_png"), exist_ok=True)

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
            if FLAGS.gen_svg_font_diffs:
                write_svg_font_diff_build(nw, svg_files)

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
