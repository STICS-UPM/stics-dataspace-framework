var path = require('path')
  , rootPath = path.normalize(__dirname + '/..')
  , templatePath = path.normalize(__dirname + '/../app/mailer/templates')
  , notifier = {
      service: 'postmark',
      APN: false,
      email: false, // true
      actions: ['comment'],
      tplPath: templatePath,
      key: 'POSTMARK_KEY',
      parseAppId: 'PARSE_APP_ID',
      parseApiKey: 'PARSE_MASTER_KEY'
    }

module.exports = {
  development: {
    db: process.env.MONGO_DB_CONNECTION_STRING || 'mongodb://localhost/lov',
    es: {
      host: process.env.ELASTIC_SEARCH_HOST,
      port: 9200,
      user: process.env.ELASTIC_SEARCH_USER,
      pass: process.env.ELASTIC_SEARCH_PASSWORD,
    },
    lov: process.env.SELF_HOST_URL || 'http://localhost:3333',
    //Path to where the output of "lov_scripts" repository have been generated
    scripts: process.env.SCRIPTS_PATH || '/share/scripts',
    //Path to "Patrones" repository
    patterns: process.env.PATTERN_PATHS || '/home/user/Patterns/Patrones',
    //Path to python environment
    python_patterns: process.env.PYTHON_PATTERNS_PATH || '/app/Patterns/env/bin/python',
    app_name: 'Ontology Hub',
    app_name_shorcut: 'STICS',
    root: rootPath,
    notifier: notifier,
    email: {
      service: 'Gmail',
      auth: {
          user: 'user@gmail.com',
          pass: 'pwd'
      }
    }
  },
  test: {
    db: process.env.MONGO_DB_CONNECTION_STRING || 'mongodb://localhost/lov',
    es: {host: 'localhost',port: 9200},
    email: {
      service: 'Gmail',
      auth: {
          user: 'user@gmail.com',
          pass: 'pwd'
      }
    }
  },
  production: {
    db: process.env.MONGO_DB_CONNECTION_STRING || 'mongodb://localhost/lov',
    es: {
      host: 'localhost',
      port: 9200,
    },
    lov: 'http://localhost:3333',
    //Path to where the output of "lov_scripts" repository have been generated
    scripts: '/home/user/scripts',
    //Path to "Patrones" repository
    patterns: '/home/user/Patterns/Patrones',
    //Path to python environment
    python_patterns: '/home/user/Patterns/env/bin/python',
    app_name: 'Example Application Name',
    app_name_shorcut: 'EAN',
    root: rootPath,
    notifier: notifier,
    email: {
      service: 'Gmail',
      auth: {
          user: 'user@gmail.com',
          pass: 'pwd'
      }
    }
  }
}
