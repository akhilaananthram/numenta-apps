# ----------------------------------------------------------------------
# Numenta Platform for Intelligent Computing (NuPIC)
# Copyright (C) 2015, Numenta, Inc.  Unless you have purchased from
# Numenta, Inc. a separate commercial license for this software code, the
# following terms and conditions apply:
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU Affero Public License for more details.
#
# You should have received a copy of the GNU Affero Public License
# along with this program.  If not, see http://www.gnu.org/licenses.
#
# http://numenta.org/licenses/
# ----------------------------------------------------------------------

"""
  Commands for use by the NuPIC pipeline script
"""

import glob
import os
import re
import shutil
import sysconfig

from pkg_resources import resource_stream

import yaml

from infrastructure.utilities import git
from infrastructure.utilities.jenkins import (createOrReplaceResultsDir,
                                              createOrReplaceArtifactsDir)
from infrastructure.utilities import diagnostics
from infrastructure.utilities.env import addNupicCoreToEnv
from infrastructure.utilities.exceptions import (CommandFailedError,
                                                 NupicBuildFailed,
                                                 PipelineError)
from infrastructure.utilities.path import changeToWorkingDir
from infrastructure.utilities.cli import runWithOutput



SCRIPTS_DIR = os.path.join(git.getGitRootFolder(), "nupic-pipeline", "scripts")
ARTIFACTS_DIR = createOrReplaceArtifactsDir()

DOXYFILE = "docs/Doxyfile"
INIT_FILE = "nupic/__init__.py"
VERSION_FILE = "VERSION"

g_config = yaml.load(resource_stream(__name__,
                                     "../../../conf/nupic/config.yaml"))



def fetchNuPIC(env, buildWorkspace, nupicRemote, nupicBranch, nupicSha, logger):
  """
    This method clones NuPIC repo if it is not present
    and checks out to required nupicBranch

    :param env: The environment which will be used before building.
    :param buildWorkspace: The workspace where NuPIC should be built
    :param nupicRemote: URL for NuPIC remote repository
    :param nupicBranch: The NuPIC branch which will be used to build
    :param nupicSha: NuPIC SHA used for current run.

    :raises: infrastructure.utilities.exceptions.MissingSHAError
      if the given SHA is not found.
  """
  try:
    with changeToWorkingDir(buildWorkspace):
      if not os.path.isdir(env["NUPIC"]):
        git.clone(nupicRemote)

    with changeToWorkingDir(env["NUPIC"]):
      git.fetch(nupicRemote, nupicBranch)
      git.resetHard(nupicSha)
  except CommandFailedError:
    logger.exception("NuPIC checkout failed with %s,"
                     " this sha might not exist.", nupicSha)



def isReleaseVersion(nupicBranch, nupicSha):
  """
    Check to see if this is a release version.

    :param nupicBranch: The NuPIC branch which will be used to build
    :param nupicSha: NuPIC SHA used for current run.

    :returns: True if nupicBranch and nupicSha are identical and match the
      pattern X.Y.Z (e.g., 0.2.3)
    :rtype: boolean
  """
  pattern = re.compile(r"\A\d+\.\d+\.\d+\Z")
  if nupicBranch == nupicSha and pattern.match(nupicSha):
    return True
  return False



def replaceInFile(fromValue, toValue, filePath):
  """
    Replaces old text with new text in a specified file.

    :param fromValue: Text to be replaced.
    :param toValue: New text.
    :param filePath: file that will be modified.
  """
  with open(filePath, "r") as f:
    contents = f.read()
  with open(filePath, "wb") as f:
    f.write(contents.replace(fromValue, toValue))



def getNuPICCoreDetails(env, nupicCoreRemote, nupicCoreSha):
  """
    Reads .nupic_modules to find nupic.core SHA and remote.

    :param env: The environment dict.

    :returns: A tuple consisting of `string` representing nupic.core remote
      and `string` representing nupicCoreSha
  """
  with changeToWorkingDir(env["NUPIC"]):
    core = {}
    execfile(".nupic_modules", {}, core)
  remote = core["NUPIC_CORE_REMOTE"] if not nupicCoreRemote else nupicCoreRemote
  committish = (
    core["NUPIC_CORE_COMMITISH"] if nupicCoreSha == "None" else nupicCoreSha)
  return remote, committish



def fetchNuPICCoreFromGH(buildWorkspace, nupicCoreRemote, nupicCoreSha, logger):
  """
    Fetch nupic.core from github

    :param buildWorkspace: The workspace where nupic.core should be built
    :param nupicCoreRemote: URL for nupic.core remote repository
    :param nupicCoreSha: The SHA of the nupic.core build that needs to be
      fetched

    :raises: infrastructure.utilities.exceptions.MissingSHAError
      if the given SHA is not found.
  """
  logger.info("Cloning nupic.core from GitHub.: {}".format(nupicCoreRemote))

  with changeToWorkingDir(buildWorkspace):
    if not os.path.isdir("nupic.core"):
      git.clone(nupicCoreRemote)

  nupicCoreDir = buildWorkspace + "/nupic.core"
  with changeToWorkingDir(nupicCoreDir):
    if nupicCoreSha:
      try:
        git.resetHard(nupicCoreSha)
      except CommandFailedError:
        logger.exception("nupic.core checkout failed with %s,"
                           " this sha might not exist.", nupicCoreSha)



def checkIfProjectExistsLocallyForSHA(project, sha, logger):
  """
    Check if project for a particular SHA has been built and cached locally.

    :param project: The project ( NuPIC or nupic.core )
    :param sha: The SHA of the project.

    :returns: True if project for a SHA exists locally.

    :rtype: boolean
  """
  logger.debug("Looking for %s locally.", project)
  return os.path.isdir("/var/build/%s/%s" % (project, sha))



def buildNuPICCore(env, nupicCoreSha, logger):
  """
    Builds nupic.core

    :param env: The environment which will be set before building.
    :param nupicCoreSha: The SHA which will be built.

    :raises
      infrastructure.utilities.exceptions.NupicBuildFailed:
      This exception is raised if build fails.
  """
  print "\n----------Building nupic.core------------"
  diagnostics.printEnv(env=env, logger=logger)
  with changeToWorkingDir(env["NUPIC_CORE_DIR"]):
    try:
      logger.debug("Building nupic.core SHA : %s ", nupicCoreSha)
      git.resetHard(nupicCoreSha)
      runWithOutput("mkdir -p build/scripts", env=env, logger=logger)
      with changeToWorkingDir("build/scripts"):
        libdir = sysconfig.get_config_var('LIBDIR')
        runWithOutput(("cmake ../../src -DCMAKE_INSTALL_PREFIX=../release "
                       "-DPYTHON_LIBRARY={}/libpython2.7.so").format(libdir),
                      env=env, logger=logger)
        runWithOutput("make -j 4", env=env, logger=logger)
        runWithOutput("make install", env=env, logger=logger)

      # need to remove this folder to allow the caching process to work
      shutil.rmtree("external/linux32arm")

      # build the distributions
      command = "python setup.py install --force"
      # Building on jenkins, not local
      if "JENKINS_HOME" in os.environ:
        command += " bdist_wheel bdist_egg upload -r numenta-pypi"
      runWithOutput(command=command, env=env, logger=logger)
    except CommandFailedError:
      raise NupicBuildFailed("nupic.core building failed.Exiting")
    except:
      raise PipelineError("nupic.core building failed due to unknown reason.")
    else:
      logger.info("nupic.core building was successful.")



# TODO Refactor and fix the cyclic calls between fullBuild() and buildNuPIC()
# Fix https://jira.numenta.com/browse/TAUR-749
def buildNuPIC(env, logger):
  """
    Builds NuPIC

    :param env: The environment which will be set before building

    :raises
      infrastructure.utilities.exceptions.NupicBuildFailed:
      This exception is raised if build fails.
  """
  print "\n----------Building NuPIC------------"
  diagnostics.printEnv(env=env, logger=logger)

  # Build
  with changeToWorkingDir(env["NUPIC"]):
    try:
      try:
        shutil.rmtree("build")
      except OSError:
        # didn't exist, so just pass
        pass
      # need to remove this folder to allow the caching process to work
      shutil.rmtree("external/linux32arm")

      # build the distributions
      command = ("python setup.py install bdist_wheel bdist_egg "
                 "--nupic-core-dir=%s" % os.path.join(env["NUPIC_CORE_DIR"],
                                                      "build", "release"))
      # Building on jenkins, not local
      if "JENKINS_HOME" in os.environ:
        command += " upload -r numenta-pypi"

      runWithOutput(command=command, env=env, logger=logger)
    except:
      logger.exception("Failed while building nupic")
      raise NupicBuildFailed("NuPIC building failed.")
    else:
      open("nupic.stamp", "a").close()
      logger.debug("NuPIC building was successful.")



def runTests(env, logger):
  """
    Runs NuPIC tests.

    :param env: The environment which will be set for runnung tests.

    :raises:
      infrastructure.utilities.exceptions.NupicBuildFailed
    if the given SHA is not found.
  """
  logger.debug("Running NuPIC Tests.")
  with changeToWorkingDir(env["NUPIC"]):
    try:
      runWithOutput("bin/py_region_test", env=env, logger=logger)
      testCommand = "scripts/run_nupic_tests -u --coverage --results xml"
      runWithOutput(testCommand, env=env, logger=logger)
    except:
      logger.exception("NuPIC Tests have failed.")
      raise
    else:
      resultFile = glob.glob("%s/tests/results/xunit/*/*.xml" % env["NUPIC"])[0]
      logger.debug("Copying results to results folder.")
      shutil.move(resultFile, createOrReplaceResultsDir())
      logger.info("NuPIC tests have passed")



def createTextFile(fileName, fileContents):
  """
    Creates file and write the text to it.

    :param fileName: Name of the file to be created
    :param fileContents: Contents of the file
    :raises IOError: if there's a problem accessing the file
  """
  with open(fileName, "w") as fHandle:
    fHandle.write(fileContents)



def cacheNuPIC(env, nupicSha, logger):
  """
    Caches a green build of NuPIC to /var/build/nupic/<SHA>

    :param env: The environment dict
    :param nupicSha: A `string` representing SHA.
  """
  cachedPath = "/var/build/nupic/%s" % nupicSha
  if not os.path.isdir(cachedPath):
    try:
      logger.info("Caching NuPIC to %s", cachedPath)
      shutil.copytree(env["NUPIC"], cachedPath)

      wheelDir = env["NUPIC"] + "/dist"
      wheelFile = glob.glob("%s/*.whl" % wheelDir)[0]
      wheelFileName = os.path.basename(wheelFile)
      contents = nupicSha + ":" + wheelFileName

      createTextFile(fileName="nupic-package-version.txt",
                     fileContents=contents)
      createTextFile(fileName="nupicSHA.txt",
                     fileContents=nupicSha)
      shutil.move("nupic-package-version.txt", ARTIFACTS_DIR)
      shutil.move("nupicSHA.txt", ARTIFACTS_DIR)
    except:
      logger.exception("Caching NuPIC failed.")
      raise
    else:
      logger.info("NuPIC cached locally.")
  else:
    logger.debug("Cached NuPIC already exists.")



def cacheNuPICCore(buildWorkspace, nupicCoreSha, logger):
  """
    Caches nupic.core to /var/build/NuPIC.core/<SHA>

    :param buildWorkspace: The buildWorkspace were nupic.core is built
    :param nupicSha: A `string` representing SHA
    :param logger: initialized logger

    :raises CommandFailedError: if the tar process fails before upload.
  """
  cachedPath = "/var/build/nupic.core/%s" % nupicCoreSha

  if not os.path.isdir(cachedPath):
    logger.info("Caching nupic.core to %s", cachedPath)

    with changeToWorkingDir(buildWorkspace):
      shutil.copytree("nupic.core", ("/var/build/nupic.core/%s/nupic.core" %
                                     nupicCoreSha))
  else:
    logger.debug("Cached nupic.core already exists.")



def installNuPICWheel(env, installDir, wheelFilePath, logger):
  """
  Install a NuPIC Wheel to a specified location.

  :param env: The environment dict
  :param installDir: The root folder to install to. NOTE: pip will automatically
    create lib/pythonX.Y/site-packages and bin folders to install libraries
    and executables to. Make sure both of those sub-folder locations are already
    on your PYTHONPATH and PATH respectively.
  :param wheelFilePath: location of the NuPIC wheel that will be installed
  :param logger: initialized logger object
  """
  try:
    if installDir is None:
      raise PipelineError("Please provide NuPIC install directory.")
    logger.debug("Installing %s to %s", wheelFilePath, installDir)
    pipCommand = ("pip install %s --install-option=--prefix=%s" %
                  (wheelFilePath, installDir))
    runWithOutput(pipCommand, env=env, logger=logger)

  except:
    logger.exception("Failed to install NuPIC wheel")
    raise CommandFailedError("Installing NuPIC wheel failed.")
  else:
    logger.debug("NuPIC wheel installed successfully.")



# TODO Refactor and fix the cyclic calls between fullBuild() and buildNuPIC()
# Fix https://jira.numenta.com/browse/TAUR-749
def fullBuild(env, buildWorkspace, nupicRemote, nupicBranch, nupicSha,
  nupicCoreRemote, nupicCoreSha, logger):
  """
    Run a full build of the NuPIC pipeline, including validating and, if
    necessary, installing nupic.core
  """
  fetchNuPIC(env, buildWorkspace, nupicRemote, nupicBranch, nupicSha, logger)

  # If this is a release version, then update __init__.py with the right
  # version number. This will ensure the proper version number is tagged in
  # the wheel file
  if isReleaseVersion(nupicBranch, nupicSha):
    with changeToWorkingDir(os.path.join(buildWorkspace, "nupic")):
      with open(VERSION_FILE, "r") as f:
        devVersion = f.read().strip()
      for targetFile in [VERSION_FILE, DOXYFILE, INIT_FILE]:
        logger.debug("\tUpdating %s...", targetFile)
        replaceInFile(devVersion, nupicSha, targetFile)

  nupicCoreRemote, nupicCoreSha = getNuPICCoreDetails(env=env,
                                                nupicCoreRemote=nupicCoreRemote,
                                                nupicCoreSha=nupicCoreSha)

  boolBuildNupicCore = False
  nupicCoreDir = ""
  if checkIfProjectExistsLocallyForSHA("nupic.core", nupicCoreSha, logger):
    nupicCoreDir = "/var/build/nupic.core/%s/nupic.core" % nupicCoreSha
    logger.debug("Found local nupic.core at: %s", nupicCoreDir)
  else:
    logger.debug("Did not find nupic.core locally.")
    fetchNuPICCoreFromGH(buildWorkspace, nupicCoreRemote, nupicCoreSha,
                         logger)
    nupicCoreDir = "%s/nupic.core" % buildWorkspace
    logger.debug("Building nupic.core at: %s", nupicCoreDir)
    boolBuildNupicCore = True

  addNupicCoreToEnv(env, nupicCoreDir)
  if boolBuildNupicCore:
    buildNuPICCore(env, nupicCoreSha, logger)

  buildNuPIC(env, logger)
  installDir = os.path.join(env["NUPIC"], "build/release")
  wheelFilePath = glob.glob("%s/dist/*.whl" % env["NUPIC"])[0]
  installNuPICWheel(env, installDir, wheelFilePath, logger)
  runTests(env, logger)

  # Cache NuPIC
  cacheNuPIC(env=env, nupicSha=nupicSha, logger=logger)

  # Cache nupic.core
  cacheNuPICCore(buildWorkspace=buildWorkspace,
                 nupicCoreSha=nupicCoreSha,
                 logger=logger)
