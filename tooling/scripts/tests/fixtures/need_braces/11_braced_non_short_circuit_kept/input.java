public class Foo
{
    public void method(Object env)
    {
        if (env != null) {
            env.destroy();
        }
        if (env == null) {
            env = new DefaultEnv();
        }
    }
}
