#!/usr/bin/env python3

import argparse
import coloredlogs
import logging
import os
import pandas as pd
import subprocess
import verboselogs
from datetime import datetime

SUBMISSION_TAG_CHECKOUT_COMMAND = "git checkout pa{0}final"
LAST_COMMIT_TIMESTAMP_COMMAND = "git log -1 --format=%ai"

BUILD_COMMAND = "mvn clean package"
TEST_COMMANDS = {
  1: 'java -cp "chocopy-ref.jar:target/assignment.jar" chocopy.ChocoPy --pa1'
     ' chocopy.pa1.StudentParser --dir ../../tests/{0} --test',
  2: 'java -cp "target/assignment.jar:chocopy-ref.jar" chocopy.ChocoPy --pa2'
     ' chocopy.pa2.StudentAnalysis --dir ../../tests/{0} --test',
  3: 'java -cp "target/assignment.jar:chocopy-ref.jar:lib/venus164.jar"'
     ' chocopy.ChocoPy --pa3 chocopy.pa3.StudentCodeGen --dir ../../tests/{0}'
     ' --run --test',
  3: 'java -cp "target/assignment.jar:chocopy-ref.jar:lib/venus164.jar"'
     ' chocopy.ChocoPy --pa3 chocopy.pa3.StudentCodeGen --dir ../../tests/{0}'
     ' --run --test'
}

TEST_LOG_PREFIXES = {
  1: "Parsing",
  2: "Reading",
  3: "Reading",
}

GRADES_COLUMNS = ["<Group>", "<Name 1>", "<Name 2>", "<Compiled>",
                  "<SampleTests>", "<ReferenceTests>", "<Benchmarktests>",
                  "<README>", "<Code>", "<Extra>", "<Late Hours>", "<Notes>"]

TEAM_MEMBER_PREFIX = "Team member {0}:"
GIT_COMMIT_TIME_FORMAT = "%Y-%m-%d %H:%M:%S %z"
DEFAULT_TIMEOUT = 30

logger = None

def setup_logging():
  global logger
  verboselogs.install()
  logger = logging.getLogger(__name__)
  coloredlogs.install(level="INFO", logger=logger)

def parse_args():
  global logger
  parser = argparse.ArgumentParser()
  parser.add_argument("-pa", help="Assignment to grade", type=int)
  parser.add_argument("-d", "--due", help="Due time timestamp, formatted as"
                                          " %Y-%m-%d %H:%M:%S %z", type=str)
  parser.add_argument("-submission", "--s",
                      help="A specific submission to grade", type=str)

  args = parser.parse_args()
  if not args.pa:
    logger.error("PA is not defined")
    exit(1)

  if not args.due:
    logger.error("Due time is not defined")
    exit(1)

  try:
    due_time = datetime.strptime(args.due.strip(), GIT_COMMIT_TIME_FORMAT)
  except ValueError:
    logger.error("Due time is not properly formatted")
    exit(1)

  return args.pa, due_time, args.s

def checkout_submission_tag(assignment_num, submission_path):
  global logger
  logger.info("Checking out submission tag")
  try:
    command = SUBMISSION_TAG_CHECKOUT_COMMAND.format(assignment_num)
    checkout_process = subprocess.run(args=command, cwd=submission_path,
                                      shell=True, stderr=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL,
                                      timeout=DEFAULT_TIMEOUT)
  except subprocess.TimeoutExpired as e:
    logger.critical("Timed out over %ds while switching to tag", e.timeout)
    return 1

  if checkout_process.returncode:
    logger.warning("Could not checkout submission tag, proceeding with master")

def get_late_hours(due_time, submission_path):
  global logger
  logger.info("Getting last commit time")
  try:
    last_commit_process = subprocess.run(args=LAST_COMMIT_TIMESTAMP_COMMAND,
                                         cwd=submission_path, shell=True,
                                         stderr=subprocess.DEVNULL,
                                         stdout=subprocess.PIPE,
                                         encoding="utf-8",
                                         timeout=DEFAULT_TIMEOUT)
  except subprocess.TimeoutExpired as e:
    logger.critical("Timed out over %ds while getting last commit", e.timeout)
    return None

  commit_time = datetime.strptime(last_commit_process.stdout.strip(),
                                  GIT_COMMIT_TIME_FORMAT)

  difference = (due_time - commit_time).total_seconds()

  if difference >= 0:
    return 0

  late_hours = int(abs(difference) // 3600)
  late_hours += 1 if abs(difference) % 3600 else 0 # Round up hours
  return late_hours

def build_submission(submission_path):
  global logger
  logger.info("Building submission")
  try:
    build_process = subprocess.run(args=BUILD_COMMAND, cwd=submission_path,
                                   shell=True, stderr=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL,
                                   timeout=DEFAULT_TIMEOUT)
  except subprocess.TimeoutExpired as e:
    logger.critical("Timed out over %ds while building repo", e.timeout)
    return 1

  if build_process.stderr:
    logger.warning("Suppressing warning/error messages from process")

  if build_process.returncode:
    logger.error("Got return value %d while building, stopping this build",
                 build_process.returncode)

  return build_process.returncode


def get_failed_tests(output, assignment_num):
  failed_tests = []

  for i, line in enumerate(output):
    split_line = line.split()
    if split_line[0] == TEST_LOG_PREFIXES[assignment_num]:
      test_name = split_line[1].split("/")[-1].replace(".out", "")
      test_passed = output[i+1].startswith("+")
      if not test_passed:
        failed_tests.append(test_name)

  return failed_tests

def run_test_folder(assignment_num, submission_path, folder):
  try:
    test_process = subprocess.run(args=TEST_COMMANDS[assignment_num].format(folder),
                                  cwd=submission_path, shell=True,
                                  stderr=subprocess.PIPE,
                                  stdout=subprocess.PIPE,
                                  encoding="utf-8",
                                  timeout=DEFAULT_TIMEOUT)
  except subprocess.TimeoutExpired as e:
    logger.critical("Timed out over %d seconds while running tests", e.timeout)
    return 1, None, []

  if test_process.stderr:
    logger.warning("Suppressing warning/error messages from process")

  if test_process.returncode:
    logger.error("Got return value %d while running tests, stopping this build",
                 test_process.returncode)
    return test_process.returncode, None, []

  output = test_process.stdout.splitlines()
  failed_tests = get_failed_tests(output, assignment_num)
  results = output[-1]
  results_split = results.split()
  num_passed, num_failed = int(results_split[1]), int(results_split[3])

  log_test_results = logger.success if not num_failed else logger.warning
  log_test_results(results[:-1]) # Strip the ending period

  return test_process.returncode, num_passed, failed_tests

def run_tests(assignment_num, submission_path):
  logger.info("Running sample tests")
  sample_retcode, sample_passed, sample_failed_names = \
    run_test_folder(assignment_num, submission_path, "sample")
  logger.info("Running reference tests")
  ref_retcode, ref_passed, ref_failed_names = \
    run_test_folder(assignment_num, submission_path, "reference")
  logger.info("Running benchmark tests")
  bench_retcode, bench_passed, bench_failed_names = \
    run_test_folder(assignment_num, submission_path, "benchmarks")

  return sample_retcode + ref_retcode + bench_retcode, sample_passed, \
    ref_passed, bench_passed, sample_failed_names + ref_failed_names + \
    bench_failed_names

def get_names(submission_path):
  global logger
  readme_file = os.path.join(submission_path, "README.md")
  if not os.path.isfile(readme_file):
    logger.info("Could not find %s in directory", readme_file)
    return "", ""

  with open(readme_file, 'r') as readme:
    lines = readme.readlines()
    name_1, name_2 = None, None

    name_1_key = TEAM_MEMBER_PREFIX.format(1)
    name_2_key = TEAM_MEMBER_PREFIX.format(2)

    for line in lines:
      line = line.strip()
      if name_1_key in line:
        name_1 = line.split(name_1_key)[1].strip()
      elif name_2_key in line:
        name_2 = line.split(name_2_key)[1].strip()

    if not (name_1 or name_2):
      logger.warning("Could not find team names")

    return name_1, name_2

def create_result_row(submission_path, submission_name, compiled,
                      sample_passed=0, hidden_passed=0, benchmark_passed=0,
                      readme=None, code=None, extra=0, late_hours=0, notes=""):
  name_1, name_2 = get_names(submission_path)
  return [submission_name, name_1, name_2, compiled, sample_passed,
          hidden_passed, benchmark_passed, readme, code, extra,
          late_hours, notes]

def grade_submission(assignment_num, due_time, submission_path, submission_name):
  global logger
  logger.info("Grading submission %s", submission_name)

  checkout_submission_tag(assignment_num, submission_path)
  late_hours = get_late_hours(due_time, submission_path)

  build_ret_code = build_submission(submission_path)

  if build_ret_code:
    return create_result_row(submission_path, submission_name, 0,
                             notes="Maven build failed", late_hours=late_hours)

  test_ret_code, sample_passed, ref_passed, bench_passed, failed_tests = \
    run_tests(assignment_num, submission_path)

  failed_tests_note = None
  if failed_tests:
    failed_tests_note = "Failed tests: {0}".format(", ".join(failed_tests))

  if test_ret_code:
    return create_result_row(submission_path, submission_name, 0,
                             late_hours=late_hours,
                             notes="Running tests failed")

  return create_result_row(submission_path, submission_name, 1, sample_passed,
                           ref_passed, bench_passed, late_hours=late_hours,
                           notes=failed_tests_note)

"""
Main function to grade a programming assignment
"""
def grade_assignment(assignment_num, due_time, submission_arg):
  global logger
  assignment_dir = "pa{0}".format(assignment_num)

  submissions_dir = os.path.join(assignment_dir, "submissions")
  if not os.path.isdir(submissions_dir):
    logger.error("Could not find %s in directory, stopping", submissions_dir)
    exit(1)

  if submission_arg:
    submission_path = os.path.join(submissions_dir, submission_arg)
    if not os.path.isdir(submissions_dir):
      logger.error("Could not find submission %s in directory, stopping", submission_arg)
      exit(1)

    result = grade_submission(assignment_num, due_time, submission_path, submission_arg)
    logger.info("Results: {0}".format(result))

  else:
    grades_file = os.path.join(assignment_dir, "grades.csv")
    if os.path.isfile(grades_file):
      logger.error("Found an existing %s in directory, stopping", grades_file)
      exit(1)

    results = []
    for submission in os.listdir(submissions_dir):
      submission_path = os.path.join(submissions_dir, submission)
      if os.path.isdir(submission_path):
        result = grade_submission(assignment_num, due_time, submission_path, submission)
        results.append(result)

    grades = pd.DataFrame(results, columns=GRADES_COLUMNS)
    grades.to_csv(grades_file, index=False)


if __name__ == "__main__":
  setup_logging()
  assignment_num, due_time, submission = parse_args()
  grade_assignment(assignment_num, due_time, submission)
