public class Demo
{
    public void run()
    {
        Class<Demo> cls = Demo.class;
        String url = cls.getResource(cls.getSimpleName() + ".class").toString();
    }
}
