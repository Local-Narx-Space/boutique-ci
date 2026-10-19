"""Keep Jenkins folder definitions and downstream job paths in sync."""
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class JenkinsJobLayoutTests(unittest.TestCase):
    def test_seed_defines_the_four_operational_folders(self):
        source = (ROOT / 'jenkins/jobs/release.groovy').read_text()
        for folder in ('Services', 'Deployments', 'Release Operations', 'Administration'):
            with self.subTest(folder=folder):
                self.assertIn(f"'{folder}'", source)
        self.assertIn('multibranchPipelineJob("Services/boutique-${service}")', source)
        self.assertIn('pipelineJob("${folder}/boutique-${job}")', source)
        self.assertIn("def folder = target ? 'Deployments' : 'Release Operations'", source)

    def test_all_cross_job_calls_use_the_folder_paths(self):
        expected = (
            ('vars/gitopsPullRequest.groovy', 'Release Operations/boutique-gitops-validate'),
            ('pipelines/gitops-validate.Jenkinsfile', 'Release Operations/boutique-release-verify'),
            ('pipelines/release-verify.Jenkinsfile', 'Deployments/boutique-deploy-dev'),
            ('pipelines/release-verify.Jenkinsfile', 'Deployments/boutique-deploy-qa'),
            ('pipelines/release-verify.Jenkinsfile', 'Deployments/boutique-deploy-prod'),
            ('vars/environmentPipeline.groovy', 'Deployments/boutique-deploy-qa'),
            ('vars/servicePipeline.groovy', 'Deployments/boutique-deploy-dev'),
        )
        for relative, job_path in expected:
            with self.subTest(file=relative, job=job_path):
                self.assertIn(job_path, (ROOT / relative).read_text())

    def test_artifact_source_is_absolute_after_folder_migration(self):
        source = (ROOT / 'vars/releaseArtifact.groovy').read_text()
        self.assertIn('projectName: "/Services/boutique-${params.SERVICE}/main"', source)

    def test_service_artifact_permission_targets_deployment_folder(self):
        source = (ROOT / 'vars/servicePipeline.groovy').read_text()
        self.assertIn("copyArtifactPermission('/Deployments/boutique-deploy-dev')", source)


if __name__ == '__main__':
    unittest.main()
