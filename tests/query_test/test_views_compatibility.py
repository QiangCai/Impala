#!/usr/bin/env python
# Copyright (c) 2012 Cloudera, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import shlex
from subprocess import call
from tests.common.test_vector import *
from tests.beeswax.impala_beeswax import ImpalaBeeswaxException
from tests.common.impala_test_suite import *

# The purpose of view compatibility testing is to check whether views created in Hive
# can be queried in Impala and vice versa. A test typically consists of
# the following actions specified in different test sections.
# 1. create a view with a certain definition using Hive and Impala
# 2. explain a "select *" query on the view created by Hive using Hive and Impala
# 3. explain a "select *" query on the view created by Impala using Hive and Impala
# For each of the steps above its corresponding test section specifies our expectations
# on whether Impala and Hive will succeed or fail.
#
# Impala and Hive's SQL dialects are not fully compatible. We intentionally rely
# on the view creation mechanism instead of just testing various SQL statements in
# Impala and Hive, because view creation transforms the original view definition into
# a so-called "extended view definition". As this process of transformation could
# potentially change in Impala and/or Hive simply testing various SQL statements
# in Impala and Hive would be insufficient.
class TestViewCompatibility(ImpalaTestSuite):
  TEST_DB_NAME = "view_compat_test_db"
  VALID_SECTION_NAMES = ["CREATE_VIEW", "CREATE_VIEW_RESULTS",\
                        "QUERY_HIVE_VIEW_RESULTS", "QUERY_IMPALA_VIEW_RESULTS"]

  @classmethod
  def get_workload(self):
    return 'functional-query'

  @classmethod
  def add_test_dimensions(cls):
    super(TestViewCompatibility, cls).add_test_dimensions()
    # don't use any exec options, running exactly once is fine
    cls.TestMatrix.clear_dimension('exec_option')
    # There is no reason to run these tests using all dimensions.
    cls.TestMatrix.add_dimension(create_uncompressed_text_dimension(cls.get_workload()))

  def setup_method(self, method):
    # cleanup and create a fresh test database
    self.cleanup_db(self.TEST_DB_NAME)
    self.execute_query("create database %s" % (self.TEST_DB_NAME))

  def teardown_method(self, method):
    self.cleanup_db(self.TEST_DB_NAME)

  def test_view_compatibility(self, vector):
    self.__run_view_compat_test_case('QueryTest/views-compatibility', vector)

  def __run_view_compat_test_case(self, test_file_name, vector):
    """
    Runs a view-compatibility test file, containing the following sections:

    ---- CREATE_VIEW
    contains a view creation statement to be executed in Impala and Hive
    ---- CREATE_VIEW_RESULTS
    whether we expect the view creation in Impala/Hive to succeed/fail
    ---- QUERY_HIVE_VIEW_RESULTS
    whether we expect to be able to query the view created by Hive in Hive/Impala
    ---- QUERY_IMPALA_VIEW_RESULTS
    whether we expect to be able to query the view created by Impala in Hive/Impala
    """

    sections = self.load_query_test_file(self.get_workload(), test_file_name,\
                                         self.VALID_SECTION_NAMES)

    for test_section in sections:
      # validate the test
      test_case = ViewCompatTestCase(test_section, test_file_name, self.TEST_DB_NAME)

      # create views in Hive and Impala checking against the expected results
      self.__exec_in_hive(test_case.get_create_view_sql('HIVE'),\
                          test_case.get_create_view_sql('HIVE'),\
                          test_case.get_create_exp_res())
      # The table may or may not have been created in Hive. And so, "invalidate metadata"
      # may throw an exception.
      try:
        self.client.invalidate_table(test_case.hive_view_name)
      except ImpalaBeeswaxException as e:
        assert "TableNotFoundException" in str(e)

      self.__exec_in_impala(test_case.get_create_view_sql('IMPALA'),\
                            test_case.get_create_view_sql('IMPALA'),\
                            test_case.get_create_exp_res())

      # explain a simple query on the view created by Hive in Hive and Impala
      if test_case.has_query_hive_section():
        exp_res = test_case.get_query_exp_res('HIVE');
        if 'HIVE' in exp_res:
          self.__exec_in_hive(test_case.get_query_view_sql('HIVE'),\
                              test_case.get_create_view_sql('HIVE'), exp_res)
        if 'IMPALA' in exp_res:
          self.__exec_in_impala(test_case.get_query_view_sql('HIVE'),\
                                test_case.get_create_view_sql('HIVE'), exp_res)

      # explain a simple query on the view created by Impala in Hive and Impala
      if test_case.has_query_impala_section():
        exp_res = test_case.get_query_exp_res('IMPALA');
        if 'HIVE' in exp_res:
          self.__exec_in_hive(test_case.get_query_view_sql('IMPALA'),\
                              test_case.get_create_view_sql('IMPALA'), exp_res)
        if 'IMPALA' in exp_res:
          self.__exec_in_impala(test_case.get_query_view_sql('IMPALA'),\
                                test_case.get_create_view_sql('IMPALA'), exp_res)

      # drop the views without checking success or failure
      self.__exec_in_hive(test_case.get_drop_view_sql('HIVE'),\
                          test_case.get_create_view_sql('HIVE'), None)
      try:
        self.client.invalidate_table(test_case.hive_view_name)
      except ImpalaBeeswaxException as e:
        assert "TableNotFoundException" in str(e)

      self.__exec_in_impala(test_case.get_drop_view_sql('IMPALA'),\
                            test_case.get_create_view_sql('IMPALA'), None)

  def __exec_in_hive(self, sql_str, create_view_sql, exp_res):
    hive_ret = call(['hive', '-e', sql_str])
    self.__cmp_expected(sql_str, create_view_sql, exp_res, "HIVE", hive_ret == 0)

  def __exec_in_impala(self, sql_str, create_view_sql, exp_res):
    success = True
    try:
      impala_ret = self.execute_query(sql_str)
      success = impala_ret.success
    except: # consider any exception a failure
      success = False
    self.__cmp_expected(sql_str, create_view_sql, exp_res, "IMPALA", success)

  def __cmp_expected(self, sql_str, create_view_sql, exp_res, engine, success):
    if exp_res is None:
      return
    if exp_res[engine] and not success:
      assert 0, '%s failed to execute\n%s\nwhile testing a view created as\n%s'\
          % (engine, sql_str, create_view_sql)
    if not exp_res[engine] and success:
      assert 0, '%s unexpectedly succeeded in executing\n%s\nwhile testing '\
          'a view created as\n%s' % (engine, create_view_sql, sql_str)

# Represents one view-compatibility test case. Performs validation of the test sections
# and provides SQL to execute for each section.
class ViewCompatTestCase(object):
  RESULT_KEYS = ["IMPALA", "HIVE"]

  def __init__(self, test_section, test_file_name, test_db_name):
    if 'CREATE_VIEW' not in test_section:
      assert 0, 'Error in test file %s. Test cases require a '\
          'CREATE_VIEW section.\n%s' %\
          (test_file_name, pprint.pformat(test_section))

    self.create_exp_res = None
    # get map of expected results from test sections
    if 'CREATE_VIEW_RESULTS' in test_section:
      self.create_exp_res =\
          self.__get_expected_results(test_section['CREATE_VIEW_RESULTS'])
    else:
      assert 0, 'Error in test file %s. Test cases require a '\
          'CREATE_VIEW_RESULTS section.\n%s' %\
          (test_file_name, pprint.pformat(test_section))

    self.query_hive_exp_res = None
    if 'QUERY_HIVE_VIEW_RESULTS' in test_section:
      self.query_hive_exp_res =\
          self.__get_expected_results(test_section['QUERY_HIVE_VIEW_RESULTS'])

    self.query_impala_exp_res = None
    if 'QUERY_IMPALA_VIEW_RESULTS' in test_section:
      self.query_impala_exp_res =\
          self.__get_expected_results(test_section['QUERY_IMPALA_VIEW_RESULTS'])

    if self.query_hive_exp_res is None and self.query_impala_exp_res is None:
      assert 0, 'Error in test file %s. Test cases require a QUERY_HIVE_VIEW_RESULTS '\
          'or QUERY_IMPALA_VIEW_RESULTS section.\n%s' %\
          (test_file_name, pprint.pformat(test_section))

    # clean test section, remove comments etc.
    self.create_view_sql = QueryTestSectionReader.build_query(test_section['CREATE_VIEW'])

    view_name = self.__get_view_name(self.create_view_sql)
    if view_name.find(".") != -1:
      assert 0, 'Error in test file %s. Found unexpected view name %s that is '\
          'qualified with a database' % (test_file_name, view_name)

    # add db prefix and suffixes to indicate which engine created the view
    self.hive_view_name = test_db_name + '.' + view_name + '_hive'
    self.impala_view_name = test_db_name + '.' + view_name + '_impala'

    self.hive_create_view_sql =\
        self.create_view_sql.replace(view_name, self.hive_view_name, 1)
    self.impala_create_view_sql =\
        self.create_view_sql.replace(view_name, self.impala_view_name, 1)

    # SQL to explain a simple query on the view created by Hive in Hive and Impala
    if self.query_hive_exp_res is not None:
      self.query_hive_view_sql = 'explain select * from %s' % (self.hive_view_name)

    # SQL to explain a simple query on the view created by Impala in Hive and Impala
    if self.query_impala_exp_res is not None:
      self.query_impala_view_sql = 'explain select * from %s' % (self.impala_view_name)

    self.drop_hive_view_sql = "drop view %s" % (self.hive_view_name)
    self.drop_impala_view_sql = "drop view %s" % (self.impala_view_name)

  def __get_view_name(self, create_view_sql):
    lexer = shlex.shlex(create_view_sql)
    tokens = list(lexer)
    # sanity check the create view statement
    if len(tokens) < 3:
      assert 0, 'Error in test. Invalid CREATE VIEW statement: %s' % (create_view_sql)
    if tokens[0].lower() != "create" or tokens[1].lower() != "view":
      assert 0, 'Error in test. Invalid CREATE VIEW statement: %s' % (create_view_sql)

    if tokens[2].lower() == "if":
      # expect an "if not exists" clause
      return tokens[5]
    else:
      # expect a create view view_name ...
      return tokens[2]

  def __get_expected_results(self, section_text):
    lines = section_text.splitlines()
    exp_res = dict()
    for line in lines:
      components = line.partition("=")
      if (components[2].lower() == 'SUCCESS'.lower()):
        exp_res[components[0]] = True
      else:
        exp_res[components[0]] = False

    # check that the results section contains at least one entry
    if not (lambda a, b: any(i in b for i in a)):
      assert 0, 'No valid entry in expected-results section. '\
      'Expected an IMPALA or HIVE entry.'
    return exp_res

  def get_create_view_sql(self, engine):
    engine = engine.upper();
    if engine == "HIVE":
      return self.hive_create_view_sql
    elif engine == "IMPALA":
      return self.impala_create_view_sql
    else:
      assert 0, "Unknown execution engine %s" % (engine)

  def get_create_exp_res(self):
    return self.create_exp_res

  def get_drop_view_sql(self, engine):
    engine = engine.upper();
    if engine == "HIVE":
      return self.drop_hive_view_sql
    elif engine == "IMPALA":
      return self.drop_impala_view_sql
    else:
      assert 0, "Unknown execution engine %s" % (engine)

  def get_query_exp_res(self, engine):
    engine = engine.upper();
    if engine == "HIVE":
      return self.query_hive_exp_res
    elif engine == "IMPALA":
      return self.query_impala_exp_res
    else:
      assert 0, "Unknown execution engine %s" % (engine)

  def get_query_view_sql(self, engine):
    engine = engine.upper();
    if engine == "HIVE":
      return self.query_hive_view_sql
    elif engine == "IMPALA":
      return self.query_impala_view_sql
    else:
      assert 0, "Unknown execution engine %s" % (engine)
    return self.query_hive_view_sql

  def has_query_hive_section(self):
    return hasattr(self, 'query_hive_view_sql')

  def has_query_impala_section(self):
    return hasattr(self, 'query_impala_view_sql')
