import BlankLayout from '@/layouts/BlankLayout.vue'
import MainLayout from '@/layouts/MainLayout.vue'

const routes = [
  {
    path: '/login',
    component: BlankLayout,
    children: [
      {
        path: '',
        name: 'Login',
        component: () => import('@/views/login/LoginPage.vue'),
        meta: { title: '登录', hidden: true }
      }
    ]
  },
  {
    path: '/403',
    component: BlankLayout,
    children: [
      {
        path: '',
        name: '403',
        component: () => import('@/views/error/403.vue'),
        meta: { title: 'Forbidden', hidden: true }
      }
    ]
  },
  {
    path: '/404',
    component: BlankLayout,
    children: [
      {
        path: '',
        name: '404',
        component: () => import('@/views/error/404.vue'),
        meta: { title: 'Not Found', hidden: true }
      }
    ]
  },
  {
    path: '/',
    component: MainLayout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/DashboardPage.vue'),
        meta: { title: '首页', icon: 'HomeFilled' }
      },
      {
        path: 'profile',
        name: 'Profile',
        component: () => import('@/views/profile/ProfilePage.vue'),
        meta: { title: '个人中心', hidden: true }
      },
      {
        path: 'students',
        name: 'Students',
        component: () => import('@/views/student/StudentList.vue'),
        meta: {
          title: '学生管理',
          icon: 'User',
          requiredRoles: ['teacher', 'admin']
        }
      },
      {
        path: 'students/evaluation',
        name: 'StudentCareEvaluation',
        component: () => import('@/views/student/StudentCareEvaluationPage.vue'),
        meta: {
          title: '研判评估',
          icon: 'Histogram',
          requiredRoles: ['teacher', 'admin']
        }
      },
      {
        path: 'students/tag-definitions',
        name: 'StudentTagDefinitions',
        component: () => import('@/views/student/StudentTagDefinitionPage.vue'),
        meta: {
          title: '标签字典管理',
          icon: 'CollectionTag',
          requiredRoles: ['admin']
        }
      },
      {
        path: 'students/bayes-rules',
        name: 'StudentCareBayesRules',
        component: () => import('@/views/student/StudentCareBayesRulePage.vue'),
        meta: {
          title: 'Bayes Rules',
          icon: 'CollectionTag',
          requiredRoles: ['admin']
        }
      },
      {
        path: 'students/tag-reviews',
        name: 'StudentTagReviews',
        component: () => import('@/views/student/StudentTagReviewPage.vue'),
        meta: {
          title: '标签审核',
          icon: 'CollectionTag',
          requiredRoles: ['teacher', 'admin']
        }
      },
      {
        path: 'teachers',
        name: 'Teachers',
        component: () => import('@/views/teacher/TeacherList.vue'),
        meta: {
          title: '教师管理',
          icon: 'Avatar',
          requiredRoles: ['admin']
        }
      },
      {
        path: 'classes',
        name: 'Classes',
        component: () => import('@/views/class_/ClassList.vue'),
        meta: {
          title: '班级管理',
          icon: 'School',
          requiredRoles: ['teacher', 'admin']
        }
      },
      {
        path: 'grouping/teacher',
        name: 'TeacherGrouping',
        component: () => import('@/views/grouping/TeacherGroupingPage.vue'),
        meta: {
          title: '教师分组管理',
          icon: 'Grid',
          requiredRoles: ['teacher']
        }
      },
      {
        path: 'placement/admin',
        name: 'AdminPlacement',
        component: () => import('@/views/placement/AdminPlacementPage.vue'),
        meta: {
          title: '校务分班管理',
          icon: 'School',
          requiredRoles: ['admin']
        }
      },
      {
        path: 'scores',
        name: 'Scores',
        component: () => import('@/views/score/ScoreList.vue'),
        meta: {
          title: '成绩管理',
          icon: 'Document',
          requiredRoles: ['student', 'teacher', 'admin']
        }
      },
      {
        path: 'ai',
        name: 'AITools',
        redirect: '/ai/comment',
        meta: { title: 'AI工具', icon: 'MagicStick' },
        children: [
          {
            path: 'comment',
            name: 'CommentGenerator',
            component: () => import('@/views/ai/CommentGenerator.vue'),
            meta: {
              title: '评语生成',
              icon: 'EditPen',
              requiredRoles: ['teacher', 'admin']
            }
          },
          {
            path: 'discipline',
            name: 'DisciplineCoach',
            component: () => import('@/views/ai/DisciplineCoach.vue'),
            meta: {
              title: '违纪话术',
              icon: 'ChatDotSquare',
              requiredRoles: ['teacher', 'admin']
            }
          },
          {
            path: 'notice',
            name: 'NoticePolisher',
            component: () => import('@/views/ai/NoticePolisher.vue'),
            meta: {
              title: '公告润色',
              icon: 'DocumentCopy',
              requiredRoles: ['teacher', 'admin']
            }
          },
          {
            path: 'rule',
            name: 'RuleBot',
            component: () => import('@/views/ai/RuleBot.vue'),
            meta: {
              title: '校规问答',
              icon: 'QuestionFilled'
            }
          },
          {
            path: 'rule-rag',
            name: 'RuleBotRag',
            component: () => import('@/views/ai/RuleBotRag.vue'),
            meta: {
              title: '新版校规问答',
              icon: 'QuestionFilled'
            }
          },
          {
            path: 'teacher-rule',
            name: 'TeacherRuleAssistant',
            component: () => import('@/views/ai/TeacherRuleAssistant.vue'),
            meta: {
              title: '教师版校规助手',
              icon: 'QuestionFilled',
              requiredRoles: ['teacher', 'admin']
            }
          },
          {
            path: 'diagnosis',
            name: 'ScoreDiagnosis',
            component: () => import('@/views/ai/ScoreDiagnosis.vue'),
            meta: {
              title: '成绩诊断',
              icon: 'TrendCharts',
              requiredRoles: ['teacher', 'admin']
            }
          },
          {
            path: 'meeting',
            name: 'MeetingPlanner',
            component: () => import('@/views/ai/MeetingPlanner.vue'),
            meta: {
              title: '班会策划',
              icon: 'Calendar',
              requiredRoles: ['teacher', 'admin']
            }
          },
          {
            path: 'interview',
            name: 'MockInterview',
            component: () => import('@/views/ai/MockInterview.vue'),
            meta: {
              title: '模拟面试',
              icon: 'Microphone'
            }
          },
          {
            path: 'group',
            name: 'GroupHelper',
            component: () => import('@/views/ai/GroupHelper.vue'),
            meta: {
              title: 'AI分组分班建议',
              icon: 'Grid',
              requiredRoles: ['teacher', 'admin']
            }
          }
        ]
      },
      {
        path: 'school-rules',
        name: 'SchoolRules',
        component: () => import('@/views/school-rule/SchoolRulePage.vue'),
        meta: {
          title: '校规管理',
          icon: 'Notebook',
          requiredRoles: ['admin']
        }
      },
      {
        path: 'rule-feedback',
        name: 'RuleFeedback',
        component: () => import('@/views/rule-feedback/RuleFeedbackPage.vue'),
        meta: {
          title: '校规反馈中心',
          icon: 'DocumentCopy',
          requiredRoles: ['admin']
        }
      }
    ]
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/404'
  }
]

export default routes


